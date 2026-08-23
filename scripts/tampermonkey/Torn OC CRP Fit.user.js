// ==UserScript==
// @name         Torn OC CRP Fit
// @namespace    http://tampermonkey.net/
// @version      1.0
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
  const DEFAULT_TABLE_URL =
    'https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/data/oc_crp_table.json';
  const SLOT_SELECTOR = '.tt-oc-highlight';
  const RESCAN_MS = 1500;

  let table = null;
  let crimesByName = new Map();
  let manualCpr = Number(GM_getValue(MANUAL_CPR_KEY, 0)) || 0;

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

  function leafElements() {
    return Array.from(document.querySelectorAll('div, span, p, li, h4, b'))
      .filter(el => el.children.length === 0 && el.textContent.trim().length > 0);
  }

  function findCrimePanels() {
    const panels = [];
    const seen = new Set();

    leafElements().forEach(el => {
      const crime = crimesByName.get(norm(el.textContent));
      if (!crime) return;

      let node = el.parentElement;
      for (let depth = 0; depth < 8 && node; depth++, node = node.parentElement) {
        const slots = findSlots(node, crime);
        if (slots.length >= 2 && !seen.has(node)) {
          seen.add(node);
          panels.push({ crime, slots });
          return;
        }
      }
    });

    return panels;
  }

  function findSlots(panel, crime) {
    const used = new Map();
    const slots = [];

    Array.from(panel.querySelectorAll('div, span, p, li, b'))
      .filter(el => el.children.length === 0)
      .forEach(el => {
        const key = basePosition(el.textContent);
        const roles = crime.rolesByBase.get(key);
        if (!roles) return;

        const index = used.get(key) || 0;
        const role = roles[index];
        if (!role) return;

        const container = slotContainer(el, panel);
        if (!container || slots.some(s => s.container === container)) return;

        used.set(key, index + 1);
        slots.push({ role, container, cpr: readCpr(container) });
      });

    return slots;
  }

  function slotContainer(labelEl, panel) {
    const marked = labelEl.closest(SLOT_SELECTOR);
    if (marked && panel.contains(marked)) return marked;

    let node = labelEl;
    for (let depth = 0; depth < 5 && node.parentElement && node.parentElement !== panel; depth++) {
      node = node.parentElement;
      if (/\d+\s*%/.test(node.textContent)) return node;
    }
    return node === labelEl ? null : node;
  }

  function readCpr(container) {
    const matches = container.textContent.match(/(\d{1,3})\s*%/g);
    if (!matches || !matches.length) return manualCpr || null;
    // The slot shows your own pass rate for that position; take the last value shown.
    return parseInt(matches[matches.length - 1], 10);
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

    const evaluated = [];
    findCrimePanels().forEach(({ crime, slots }) => {
      slots.forEach(slot => {
        const cpr = slot.cpr;
        const eligible = cpr !== null && cpr >= slot.role.min_cpr;
        evaluated.push({
          crime,
          role: slot.role,
          container: slot.container,
          cpr,
          eligible,
          score: eligible ? slot.role.weight * (cpr / 100) : -1
        });
      });
    });

    evaluated.sort((a, b) => b.score - a.score);
    const best = evaluated.filter(e => e.eligible).slice(0, 3);

    evaluated.forEach(entry => {
      entry.container.classList.add('crp-slot');
      if (best[0] === entry) entry.container.classList.add('crp-best');
      else if (entry.eligible) entry.container.classList.add('crp-ok');
      else entry.container.classList.add('crp-low');

      const badge = document.createElement('span');
      badge.className = 'crp-badge';
      badge.textContent = `w ${(entry.role.weight * 100).toFixed(1)}% · need ${entry.role.min_cpr}`;
      entry.container.appendChild(badge);
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
      panel.innerHTML = '<h4>OC CRP Fit</h4><div class="crp-muted">No crime slots detected.</div>';
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
      `<h4>OC CRP Fit — best of ${total} slots</h4>` +
      (items ? `<ol>${items}</ol>` : '<div class="crp-muted">No slot meets your CPR.</div>');
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
