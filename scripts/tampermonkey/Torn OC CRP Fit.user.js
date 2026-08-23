// ==UserScript==
// @name         Torn OC CRP Fit
// @namespace    http://tampermonkey.net/
// @version      1.1
// @description  Highlights the organised crime slots that best fit your CPR, using the faction CRP/weight table.
// @match        https://www.torn.com/factions.php?step=your&type=1*
// @grant        GM_registerMenuCommand
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @homepageURL  https://github.com/xDp64xG/Torn-Intel
// @supportURL   https://github.com/xDp64xG/Torn-Intel/issues
// @connect      raw.githubusercontent.com
// @updateURL    https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/Torn%20OC%20CRP%20Fit.user.js
// @downloadURL  https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/Torn%20OC%20CRP%20Fit.user.js
// ==/UserScript==

(function () {
  'use strict';

  const TABLE_URL_KEY = 'gts_crp_table_url';
  const TABLE_CACHE_KEY = 'gts_crp_table_cache';
  const MANUAL_CPR_KEY = 'gts_crp_manual_cpr';
  const DEBUG_KEY = 'gts_crp_debug';
  const DEFAULT_TABLE_URL =
    'https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/data/oc_crp_table.json';
  const SLOT_HINTS = '.tt-oc-highlight, [class*="waitingJoin"]';
  const CRIME_LIST = '#faction-crimes-root';
  const RESCAN_MS = 1200;

  let table = null;
  let crimesByName = new Map();
  let manualCpr = Number(GM_getValue(MANUAL_CPR_KEY, 0)) || 0;
  let debug = GM_getValue(DEBUG_KEY, false);

  GM_addStyle(`
    .crp-slot { position: relative; outline-offset: -2px; }
    .crp-best { outline: 2px solid #4caf50 !important; background: rgba(76,175,80,0.12) !important; }
    .crp-ok { outline: 2px solid #8bc34a !important; }
    .crp-low { outline: 2px dashed #e53935 !important; background: rgba(229,57,53,0.10) !important; }
    .crp-badge {
      position: absolute; top: 2px; right: 2px; z-index: 5;
      font-size: 10px; line-height: 12px; padding: 1px 4px; border-radius: 3px;
      background: #222; color: #fff; pointer-events: none; white-space: nowrap;
    }
    #crp-panel {
      position: fixed; right: 12px; bottom: 12px; z-index: 9999; width: 250px;
      background: #1b1b1b; color: #eee; border: 1px solid #444; border-radius: 6px;
      font: 12px/1.4 Arial, sans-serif; padding: 8px;
    }
    #crp-panel h4 { margin: 0 0 6px; font-size: 12px; color: #8bc34a; }
    #crp-panel ol { margin: 0; padding-left: 16px; }
    #crp-panel .crp-muted { color: #999; }
  `);

  GM_registerMenuCommand('Set CRP table URL', () => {
    const url = prompt('URL of oc_crp_table.json:', tableUrl());
    if (url) {
      GM_setValue(TABLE_URL_KEY, url.trim());
      loadTable(true).then(scan);
    }
  });

  GM_registerMenuCommand('Set fallback CPR', () => {
    const value = prompt('Your CPR to use when the page does not show one (0 = off):', manualCpr);
    if (value !== null) {
      manualCpr = Number(value) || 0;
      GM_setValue(MANUAL_CPR_KEY, manualCpr);
      scan();
    }
  });

  GM_registerMenuCommand('Refresh CRP table', () => loadTable(true).then(scan));

  GM_registerMenuCommand('Toggle CRP debug logging', () => {
    debug = !debug;
    GM_setValue(DEBUG_KEY, debug);
    scan();
  });

  function log(...args) {
    if (debug) console.log('[CRP Fit]', ...args);
  }

  function tableUrl() {
    return GM_getValue(TABLE_URL_KEY, DEFAULT_TABLE_URL);
  }

  function loadTable(force) {
    const cached = GM_getValue(TABLE_CACHE_KEY, '');
    if (cached && !force) {
      applyTable(JSON.parse(cached));
      return Promise.resolve(table);
    }
    return new Promise(resolve => {
      GM_xmlhttpRequest({
        method: 'GET',
        url: tableUrl(),
        onload: res => {
          try {
            const data = JSON.parse(res.responseText);
            GM_setValue(TABLE_CACHE_KEY, res.responseText);
            applyTable(data);
          } catch (err) {
            console.error('[CRP Fit] bad table payload', err);
            if (cached) applyTable(JSON.parse(cached));
          }
          resolve(table);
        },
        onerror: () => {
          if (cached) applyTable(JSON.parse(cached));
          resolve(table);
        }
      });
    });
  }

  function applyTable(data) {
    table = data;
    crimesByName = new Map();
    (data.crimes || []).forEach(crime => {
      crimesByName.set(norm(crime.name), crime);
      crime.rolesByBase = groupRoles(crime.roles);
    });
  }

  function norm(text) {
    return (text || '').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function basePosition(position) {
    return norm(position.replace(/#\d+\s*$/, ''));
  }

  // "Muscle #1"/"Muscle #2" appear on the page as two plain "Muscle" slots,
  // so keep them ordered per base name and consume them in DOM order.
  function groupRoles(roles) {
    const grouped = new Map();
    roles.forEach(role => {
      const key = basePosition(role.position);
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(role);
    });
    return grouped;
  }

  function leafElements(root) {
    return Array.from((root || document).querySelectorAll('div, span, p, li, h4, b'))
      .filter(el => el.children.length === 0 && el.textContent.trim().length > 0);
  }

  // A slot in a recruiting crime carries the TornTools highlight class or Torn's
  // hashed "waitingJoin" class; its parent element is the row holding every slot.
  function findSlotRows() {
    const root = document.querySelector(CRIME_LIST) || document.body;
    const rows = new Set();
    root.querySelectorAll(SLOT_HINTS).forEach(hint => {
      const row = hint.parentElement;
      if (row && row.children.length) rows.add(row);
    });
    return Array.from(rows);
  }

  function findCrimeCard(row) {
    let node = row;
    for (let depth = 0; depth < 10 && node; depth++, node = node.parentElement) {
      const crime = crimeIn(node);
      if (crime) return { card: node, crime };
    }
    return null;
  }

  function crimeIn(node) {
    for (const el of leafElements(node)) {
      const crime = crimesByName.get(norm(el.textContent));
      if (crime) return crime;
    }
    return null;
  }

  function isRecruiting(card) {
    return /recruiting|waiting|join/i.test(card.textContent);
  }

  function isEmptySlot(slot) {
    if (/waitingjoin/i.test(slot.className)) return true;
    if (slot.querySelector('a[href*="profiles.php"], a[href*="XID="]')) return false;
    return /\bjoin\b|empty|available/i.test(slot.textContent);
  }

  function positionOf(slot, crime) {
    for (const el of leafElements(slot)) {
      const key = basePosition(el.textContent);
      if (crime.rolesByBase.has(key)) return key;
    }
    const key = basePosition(slot.textContent);
    return crime.rolesByBase.has(key) ? key : null;
  }

  function readCpr(slot) {
    const labelled = slot.textContent.match(/cpr\D{0,12}(\d{1,3})/i);
    if (labelled) return parseInt(labelled[1], 10);
    const percents = slot.textContent.match(/(\d{1,3})\s*%/g);
    if (percents && percents.length) return parseInt(percents[percents.length - 1], 10);
    return manualCpr || null;
  }

  function collectSlots() {
    const results = [];

    findSlotRows().forEach(row => {
      const match = findCrimeCard(row);
      if (!match) {
        log('slot row without a known crime name', row);
        return;
      }
      const { card, crime } = match;
      if (!isRecruiting(card)) return;

      const used = new Map();
      Array.from(row.children).forEach(slot => {
        const key = positionOf(slot, crime);
        if (!key) return;

        const index = used.get(key) || 0;
        used.set(key, index + 1);
        const role = crime.rolesByBase.get(key)[index];
        if (!role || !isEmptySlot(slot)) return;

        results.push({ crime, role, slot, cpr: readCpr(slot) });
      });
    });

    log('open slots found', results.length, results);
    return results;
  }

  function clearMarks() {
    document.querySelectorAll('.crp-badge').forEach(el => el.remove());
    document.querySelectorAll('.crp-slot').forEach(el => {
      el.classList.remove('crp-slot', 'crp-best', 'crp-ok', 'crp-low');
    });
  }

  let marking = false;

  function scan() {
    if (!table || !isOcPage()) {
      clearMarks();
      const panel = document.getElementById('crp-panel');
      if (panel) panel.remove();
      return;
    }
    marking = true;
    clearMarks();

    const evaluated = collectSlots().map(entry => {
      const eligible = entry.cpr !== null && entry.cpr >= entry.role.min_cpr;
      return Object.assign(entry, {
        eligible,
        score: eligible ? entry.role.weight * (entry.cpr / 100) : -1
      });
    });

    evaluated.sort((a, b) => b.score - a.score);
    const best = evaluated.filter(e => e.eligible).slice(0, 3);

    evaluated.forEach(entry => {
      entry.slot.classList.add('crp-slot');
      if (best[0] === entry) entry.slot.classList.add('crp-best');
      else if (entry.eligible) entry.slot.classList.add('crp-ok');
      else entry.slot.classList.add('crp-low');

      const badge = document.createElement('span');
      badge.className = 'crp-badge';
      badge.textContent = `w ${(entry.role.weight * 100).toFixed(1)}% · need ${entry.role.min_cpr}`;
      entry.slot.appendChild(badge);
    });

    renderPanel(best, evaluated.length);
    setTimeout(() => { marking = false; }, 0);
  }

  function renderPanel(best, total) {
    let panel = document.getElementById('crp-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'crp-panel';
      document.body.appendChild(panel);
    }

    if (!total) {
      panel.innerHTML =
        '<h4>OC CRP Fit</h4><div class="crp-muted">No open slots detected on recruiting crimes.</div>';
      return;
    }

    const items = best
      .map(
        e =>
          `<li><b>${e.crime.name}</b> — ${e.role.position}<br>` +
          `<span class="crp-muted">your ${e.cpr} / need ${e.role.min_cpr} · weight ${(e.role.weight * 100).toFixed(1)}%</span></li>`
      )
      .join('');

    panel.innerHTML =
      `<h4>OC CRP Fit — best of ${total} open slots</h4>` +
      (items ? `<ol>${items}</ol>` : '<div class="crp-muted">No open slot meets your CPR.</div>');
  }

  function isOcPage() {
    return (
      location.pathname === '/factions.php' &&
      location.search.includes('step=your') &&
      location.search.includes('type=1') &&
      location.hash.includes('tab=crimes')
    );
  }

  let timer = null;
  function schedule() {
    if (marking) return;
    clearTimeout(timer);
    timer = setTimeout(scan, RESCAN_MS);
  }

  loadTable(false).then(() => {
    scan();
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    window.addEventListener('hashchange', schedule);
  });
})();
