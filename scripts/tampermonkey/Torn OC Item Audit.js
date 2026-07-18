// ==UserScript==
// @name         Torn OC Item Audit
// @namespace    GTS
// @version      1.5
// @match        https://www.torn.com/factions.php*
// @grant        GM_registerMenuCommand
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_xmlhttpRequest
// @connect      api.torn.com
// @updateURL    https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/Torn%20OC%20Item%20Audit.js
// @downloadURL  https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/Torn%20OC%20Item%20Audit.js
// ==/UserScript==

(function () {
  'use strict';

  const API_KEY_STORAGE = 'gts_oc_item_audit_api_key';
  const ITEM_NAME_CACHE = 'gts_oc_item_name_cache';
  const REFRESH_MINUTES = 5;

  let apiKey = GM_getValue(API_KEY_STORAGE, '');
  let itemNames = JSON.parse(localStorage.getItem(ITEM_NAME_CACHE) || '{}');
  let ocData = null;

  let armouryAudit = {
    correct: [],
    wrongHolder: [],
    returnable: [],
    stockNeeded: []
  };

  GM_registerMenuCommand('Set OC Item Audit API Key', () => {
    const key = prompt('Enter Torn API key:', apiKey || '');
    if (key) {
      apiKey = key.trim();
      GM_setValue(API_KEY_STORAGE, apiKey);
      refreshData();
    }
  });

  GM_registerMenuCommand('Refresh OC Item Audit', () => refreshData());

  function isUtilitiesPage() {
    return location.href.includes('factions.php')
      && location.href.includes('step=your')
      && location.href.includes('tab=armoury')
      && location.href.includes('sub=utilities');
  }

  function requestJson(url, useHeader = true) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: 'GET',
        url,
        headers: useHeader ? { Authorization: `ApiKey ${apiKey}` } : {},
        onload: res => {
          try {
            const data = JSON.parse(res.responseText);
            if (data.error) reject(data.error);
            else resolve(data);
          } catch (e) {
            reject(e);
          }
        },
        onerror: reject
      });
    });
  }

  async function refreshData() {
    makePanel();

    if (!apiKey) {
      setPanel(`<div class="badText">No API key set. Use Tampermonkey menu → Set OC Item Audit API Key.</div>`);
      return;
    }

    setPanel(`<div>Loading OC item data...</div>`);

    try {
      const data = await requestJson(
        'https://api.torn.com/v2/faction/basic,crimes,members?cat=available,completed&offset=0&striptags=true&comment=GTS-OC-Item-Audit'
      );

      ocData = buildOCData(data);

      await loadMissingItemNames();

      applyItemNamesToOCData();

      scanArmoury();
      renderPanel();
    } catch (e) {
      setPanel(`<div class="badText">API error: ${escapeHtml(e.error || e.message || String(e))}</div>`);
    }
  }

  function buildOCData(data) {
    const members = {};
    const needed = [];
    const neededByUserItem = {};
    const neededByItem = {};

    for (const m of data.members || []) {
      members[m.id] = {
        id: m.id,
        name: m.name,
        inOC: false
      };
    }

    for (const crime of data.crimes || []) {
      if (!['Recruiting', 'Planning'].includes(crime.status)) continue;

      for (const slot of crime.slots || []) {
        const user = slot.user;
        const item = slot.item_requirement;

        if (user?.id && members[user.id]) {
          members[user.id].inOC = true;
        }

        if (!user?.id || !item?.id) continue;

        const entry = {
          userId: user.id,
          userName: members[user.id]?.name || user.name || user.id,
          itemId: Number(item.id),
          itemName: item.name || itemNames[item.id] || `Item ${item.id}`,
          isAvailable: item.is_available === true,
          reusable: item.is_reusable === true,
          crimeId: crime.id,
          crimeName: crime.name,
          crimeStatus: crime.status,
          difficulty: crime.difficulty,
          position: slot.position,
          cpr: slot.checkpoint_pass_rate || 0
        };

        needed.push(entry);
        neededByUserItem[`${entry.userId}|${entry.itemId}`] = entry;

        if (!neededByItem[entry.itemId]) neededByItem[entry.itemId] = [];
        neededByItem[entry.itemId].push(entry);
      }
    }

    const notInOC = Object.values(members).filter(m => !m.inOC);

    return {
      needed,
      neededByUserItem,
      neededByItem,
      notInOC,
      updated: Date.now()
    };
  }

  async function loadMissingItemNames() {
    if (!ocData) return;

    const missingIds = [...new Set(
      ocData.needed
        .map(x => x.itemId)
        .filter(id => !itemNames[id])
    )];

    if (!missingIds.length) return;

    const url = `https://api.torn.com/torn/${missingIds.join(',')}?selections=items&key=${encodeURIComponent(apiKey)}&comment=GTS-OC-Item-Names`;

    try {
      const data = await requestJson(url, false);

      if (data.items) {
        for (const [id, item] of Object.entries(data.items)) {
          if (item?.name) itemNames[id] = item.name;
        }

        localStorage.setItem(ITEM_NAME_CACHE, JSON.stringify(itemNames));
      }
    } catch (e) {
      console.warn('[OC Item Audit] Item name lookup failed:', e);
    }
  }

  function applyItemNamesToOCData() {
    if (!ocData) return;

    for (const entry of ocData.needed) {
      if (itemNames[entry.itemId]) {
        entry.itemName = itemNames[entry.itemId];
      }
    }
  }

  function scanArmoury() {
    if (!ocData || !isUtilitiesPage()) return;

    armouryAudit = {
      correct: [],
      wrongHolder: [],
      returnable: [],
      stockNeeded: []
    };

    document.querySelectorAll('li.tt-overlay-ignore').forEach(row => {
      clearRow(row);

      const item = readUtilityRow(row);
      if (!item) return;

      if (item.itemName && !itemNames[item.itemId]) {
        itemNames[item.itemId] = item.itemName;
        localStorage.setItem(ITEM_NAME_CACHE, JSON.stringify(itemNames));
        applyItemNamesToOCData();
      }

      const neededByHolder = ocData.neededByUserItem[`${item.holderId}|${item.itemId}`];
      const neededBySomeone = ocData.neededByItem[item.itemId] || [];

      if (!item.holderId) {
        if (neededBySomeone.length) {
          armouryAudit.stockNeeded.push({ item, neededBySomeone });
          badge(row, `NEEDED x${neededBySomeone.length}`, 'good');
        }
        return;
      }

      if (neededByHolder) {
        armouryAudit.correct.push({ item, neededByHolder });
        row.classList.add('gts-oc-correct');
        badge(row, 'CORRECT HOLDER', 'good');
        note(row, `Needed for: ${neededByHolder.crimeName}`);
        return;
      }

      if (neededBySomeone.length) {
        armouryAudit.wrongHolder.push({ item, neededBySomeone });
        row.classList.add('gts-oc-wrong');
        badge(row, 'WRONG HOLDER', 'warn');
        note(row, `Needed by: ${neededBySomeone.map(e => e.userName).join(', ')}`);
        return;
      }

      armouryAudit.returnable.push({ item });
      row.classList.add('gts-oc-return');
      badge(row, 'RETURN ITEM', 'bad');
      note(row, 'Not needed by any active Planning/Recruiting OC.');
    });
  }

  function readUtilityRow(row) {
    const img = row.querySelector('.img-wrap[data-itemid]');
    const name = row.querySelector('.name');
    const loaned = row.querySelector('.loaned');

    if (!img || !name || !loaned) return null;

    const itemId = Number(img.dataset.itemid);
    const itemName = name.textContent.replace(/x\s*\d+/i, '').trim();

    const holderLink = loaned.querySelector('a[href*="profiles.php?XID="]');
    let holderId = 0;
    let holderName = '';

    if (holderLink) {
      const match = holderLink.href.match(/XID=(\d+)/);
      holderId = match ? Number(match[1]) : 0;
      holderName = holderLink.textContent.trim();
    }

    return {
      itemId,
      itemName,
      holderId,
      holderName
    };
  }

  function renderPanel() {
    if (!ocData) return;

    applyItemNamesToOCData();

    const missing = ocData.needed.filter(x => !x.isAvailable);
    const available = ocData.needed.filter(x => x.isAvailable);

    const returnableHtml = armouryAudit.returnable.length
      ? armouryAudit.returnable.map(x => `
        <div class="row">
          <b class="badText">${escapeHtml(x.item.itemName)}</b><br>
          Held by:
          <a href="/profiles.php?XID=${x.item.holderId}" target="_blank">
            ${escapeHtml(x.item.holderName)}
          </a><br>
          <span class="muted">Not needed by any active OC.</span>
        </div>
      `).join('')
      : `<div class="row muted">No unnecessary loaned OC items detected.</div>`;

    const wrongHolderHtml = armouryAudit.wrongHolder.length
      ? armouryAudit.wrongHolder.map(x => `
        <div class="row">
          <b class="warnText">${escapeHtml(x.item.itemName)}</b><br>
          Held by:
          <a href="/profiles.php?XID=${x.item.holderId}" target="_blank">
            ${escapeHtml(x.item.holderName)}
          </a><br>
          Needed by: ${x.neededBySomeone.map(e => escapeHtml(e.userName)).join(', ')}
        </div>
      `).join('')
      : `<div class="row muted">No wrong-holder items detected.</div>`;

    const requiredHtml = ocData.needed.map(e => `
      <div class="row">
        <b class="${e.isAvailable ? 'goodText' : 'badText'}">${escapeHtml(e.itemName)}</b>
        ${e.reusable ? '<span class="muted">(∞)</span>' : ''}
        <br>
        Needed by:
        <a href="/profiles.php?XID=${e.userId}" target="_blank">${escapeHtml(e.userName)}</a>
        <br>
        <span class="muted">Lv${e.difficulty} ${escapeHtml(e.crimeName)} • ${escapeHtml(e.position)} • CPR ${e.cpr}%</span>
        <br>
        <a href="/factions.php?step=your&type=12#/tab=crimes&crimeId=${e.crimeId}" target="_blank">Open Crime</a>
      </div>
    `).join('');

    setPanel(`
      <div class="summary">
        <b>OC Item Audit</b><br>
        <span class="badText">Missing items: ${missing.length}</span><br>
        <span class="goodText">Available/correct: ${available.length}</span><br>
        <span class="badText">Return items: ${armouryAudit.returnable.length}</span><br>
        <span class="warnText">Wrong holder: ${armouryAudit.wrongHolder.length}</span><br>
        <span class="muted">Members not in OC: ${ocData.notInOC.length}</span><br>
        <span class="muted">Updated: ${new Date(ocData.updated).toLocaleTimeString()}</span>
      </div>

      <hr>

      <div class="section-title">Return / Not Needed Items</div>
      ${returnableHtml}

      <hr>

      <div class="section-title">Wrong Holder / Needed Elsewhere</div>
      ${wrongHolderHtml}

      <hr>

      <div class="section-title">OC Required Items</div>
      ${requiredHtml || '<div class="row muted">No active OC item requirements found.</div>'}
    `);
  }

  function makePanel() {
    if (document.querySelector('#gts-oc-audit-panel')) return;

    const style = document.createElement('style');
    style.textContent = `
      #gts-oc-audit-panel {
        position: fixed;
        right: 12px;
        bottom: 80px;
        width: 410px;
        max-height: 600px;
        overflow: hidden;
        background: #111;
        color: #eee;
        border: 2px solid #c9a44c;
        border-radius: 8px;
        z-index: 999999;
        font: 12px Arial, sans-serif;
        box-shadow: 0 0 12px #000;
      }

      #gts-oc-audit-head {
        background: #5a0808;
        color: #f0d27a;
        padding: 8px;
        display: flex;
        justify-content: space-between;
        cursor: move;
        user-select: none;
      }

      #gts-oc-audit-body {
        padding: 8px;
        max-height: 550px;
        overflow-y: auto;
      }

      #gts-oc-audit-panel button {
        background: #222;
        color: #f0d27a;
        border: 1px solid #c9a44c;
        border-radius: 4px;
        cursor: pointer;
      }

      #gts-oc-audit-panel .row {
        padding: 6px;
        border-bottom: 1px solid #333;
        line-height: 1.4;
      }

      #gts-oc-audit-panel a { color: #7fb6ff; }
      #gts-oc-audit-panel .muted { color: #aaa; }
      #gts-oc-audit-panel .goodText { color: #7CFC98; }
      #gts-oc-audit-panel .badText { color: #ff8080; }
      #gts-oc-audit-panel .warnText { color: #f0d27a; }

      .section-title {
        color: #f0d27a;
        font-weight: bold;
        padding: 4px 0;
      }

      li.gts-oc-correct {
        outline: 2px solid #39c56b !important;
        background: rgba(57,197,107,.15) !important;
      }

      li.gts-oc-wrong {
        outline: 2px solid #f0d27a !important;
        background: rgba(240,210,122,.18) !important;
      }

      li.gts-oc-return {
        outline: 2px solid #ff5555 !important;
        background: rgba(255,85,85,.18) !important;
      }

      .gts-oc-badge {
        display: inline-block;
        margin-left: 6px;
        padding: 2px 5px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: bold;
      }

      .gts-oc-good {
        background:#143d22;
        color:#b6ffcb;
        border:1px solid #39c56b;
      }

      .gts-oc-warn {
        background:#3f330f;
        color:#ffe58a;
        border:1px solid #f0d27a;
      }

      .gts-oc-bad {
        background:#5a0808;
        color:white;
        border:1px solid #ff8080;
      }

      .gts-oc-note {
        display:block;
        font-size:10px;
        margin-top:3px;
        color:#f0d27a;
      }
    `;
    document.head.appendChild(style);

    const panel = document.createElement('div');
    panel.id = 'gts-oc-audit-panel';
    panel.innerHTML = `
      <div id="gts-oc-audit-head">
        <b>OC Item Audit</b>
        <span>
          <button id="gts-oc-audit-refresh">Refresh</button>
          <button id="gts-oc-audit-toggle">_</button>
        </span>
      </div>
      <div id="gts-oc-audit-body"></div>
    `;
    document.body.appendChild(panel);

    document.querySelector('#gts-oc-audit-refresh').onclick = () => refreshData();
    document.querySelector('#gts-oc-audit-toggle').onclick = () => {
      const body = document.querySelector('#gts-oc-audit-body');
      body.style.display = body.style.display === 'none' ? '' : 'none';
    };

    makeDraggable(panel, document.querySelector('#gts-oc-audit-head'));
  }

  function makeDraggable(panel, handle) {
    let dragging = false;
    let offsetX = 0;
    let offsetY = 0;

    handle.addEventListener('mousedown', e => {
      if (e.target.tagName === 'BUTTON') return;

      dragging = true;
      offsetX = panel.offsetLeft - e.clientX;
      offsetY = panel.offsetTop - e.clientY;

      panel.style.right = 'auto';
      panel.style.bottom = 'auto';
    });

    document.addEventListener('mouseup', () => {
      dragging = false;
    });

    document.addEventListener('mousemove', e => {
      if (!dragging) return;

      panel.style.left = `${e.clientX + offsetX}px`;
      panel.style.top = `${e.clientY + offsetY}px`;
    });
  }

  function setPanel(html) {
    makePanel();
    document.querySelector('#gts-oc-audit-body').innerHTML = html;
  }

  function clearRow(row) {
    row.classList.remove('gts-oc-correct', 'gts-oc-wrong', 'gts-oc-return');
    row.querySelectorAll('.gts-oc-badge, .gts-oc-note').forEach(x => x.remove());
  }

  function badge(row, text, type) {
    const el = document.createElement('span');
    el.className = `gts-oc-badge gts-oc-${type}`;
    el.textContent = text;
    const target = row.querySelector('.name') || row;
    target.appendChild(el);
  }

  function note(row, text) {
    const el = document.createElement('span');
    el.className = 'gts-oc-note';
    el.textContent = text;
    const target = row.querySelector('.loaned') || row.querySelector('.name') || row;
    target.appendChild(el);
  }

  function escapeHtml(str) {
    return String(str ?? '').replace(/[&<>"']/g, s => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[s]));
  }

  makePanel();
  refreshData();

  setInterval(() => {
    scanArmoury();
    renderPanel();
  }, 2000);

  setInterval(refreshData, REFRESH_MINUTES * 60 * 1000);
})();