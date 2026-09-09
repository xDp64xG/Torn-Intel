// ==UserScript==
// @name         Torn Faction Give Guard
// @namespace    http://tampermonkey.net/
// @author       TornIntel
// @version      1.5.0
// @description  Shows a member's faction vault balance while you type their name and blocks giving them more than they have. Desktop and Torn PDA.
// @match        https://www.torn.com/factions.php?step=your&type=1#/tab=controls*
// @match        
// @grant        GM_registerMenuCommand
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_addStyle
// @grant        GM_xmlhttpRequest
// @connect      api.torn.com
// @homepageURL  https://github.com/xDp64xG/Torn-Intel
// @supportURL   https://github.com/xDp64xG/Torn-Intel/issues
// @updateURL    https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/Torn%20Faction%20Give%20Guard.user.js
// @downloadURL  https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/Torn%20Faction%20Give%20Guard.user.js
// ==/UserScript==

(function () {
  'use strict';

  const VERSION = '1.5.0';
  const STORE_PREFIX = 'tfgg_';
  const API_KEY_KEY = 'api_key';
  const API_ENABLED_KEY = 'api_enabled';
  const ENFORCE_KEY = 'enforce';
  const DEBUG_KEY = 'debug';
  const CACHE_KEY = 'balance_cache';
  const CACHE_TTL_MS = 60 * 1000;
  const STALE_REFRESH_MS = 15 * 1000;
  const RESCAN_MS = 1000;
  const CHIP_CLASS = 'tfgg-chip';
  const MODAL_ID = 'tfgg-modal';
  // Torn wraps the faction give/take money block in a hashed class such as money___DbkSX.
  const GIVE_SCOPE_SELECTOR = '[class*="money___"], [class*="points___"], [class*="give___"]';
  // Torn prints "Name`s current balance is $-36,083,851" once a member is selected.
  const BALANCE_TEXT_RE = /^(.*?)[\u2019'`\u00b4]s\s+current balance is\s*\$?\s*(-?[\d,]+)/i;
  // The "$" shortcut button fills the field with the whole vault, so it needs its own guard.
  const MAX_BUTTON_SELECTOR = 'input.wai-btn, .input-money-symbol';
  const NON_VALUE_INPUT_TYPES = ['hidden', 'checkbox', 'radio', 'button', 'submit', 'reset', 'image', 'file'];

  // Torn PDA substitutes this literal with the user's key before running the script.
  const PDA_API_KEY = '###PDA-APIKEY###';

  const IS_TOUCH = (matchMedia('(pointer: coarse)').matches || (navigator.maxTouchPoints || 0) > 0);
  const IS_TORN_PDA = /torn\s*pda|tornpda/i.test(navigator.userAgent || '') || IS_TOUCH;

  const state = {
    balances: null,
    fetchedAt: 0,
    fetching: null,
    lastError: null,
    bypass: null,
    watched: new WeakSet(),
    chips: new WeakMap(),
    containers: [],
    rescanTimer: null
  };

  /* ------------------------------------------------------------------ storage */

  function recall(key, fallback) {
    const full = STORE_PREFIX + key;
    try {
      const raw = window.localStorage.getItem(full);
      if (raw !== null) return JSON.parse(raw);
    } catch (e) { /* fall through */ }
    try {
      if (typeof GM_getValue === 'function') {
        const value = GM_getValue(full, null);
        if (value !== null && value !== undefined) {
          return typeof value === 'string' ? JSON.parse(value) : value;
        }
      }
    } catch (e) { /* fall through */ }
    return fallback;
  }

  function store(key, value) {
    const full = STORE_PREFIX + key;
    const raw = JSON.stringify(value);
    try { window.localStorage.setItem(full, raw); } catch (e) { /* ignore */ }
    try { if (typeof GM_setValue === 'function') GM_setValue(full, raw); } catch (e) { /* ignore */ }
  }

  function debugEnabled() { return recall(DEBUG_KEY, false) === true; }
  function enforceEnabled() { return recall(ENFORCE_KEY, true) !== false; }
  function apiEnabled() { return recall(API_ENABLED_KEY, false) === true; }

  function log(...args) {
    if (debugEnabled()) console.log('[Give Guard]', ...args);
  }

  function apiKey() {
    if (PDA_API_KEY.indexOf('###') !== 0) return PDA_API_KEY.trim();
    return String(recall(API_KEY_KEY, '') || '').trim();
  }

  /* ------------------------------------------------------------------ helpers */

  function addStyle(css) {
    try {
      if (typeof GM_addStyle === 'function') { GM_addStyle(css); return; }
    } catch (e) { /* fall through */ }
    const style = document.createElement('style');
    style.textContent = css;
    (document.head || document.documentElement).appendChild(style);
  }

  function registerMenuCommand(label, handler) {
    try {
      if (typeof GM_registerMenuCommand === 'function') GM_registerMenuCommand(label, handler);
    } catch (e) { /* ignore */ }
  }

  function httpJson(url) {
    if (typeof GM_xmlhttpRequest === 'function') {
      return new Promise((resolve, reject) => {
        GM_xmlhttpRequest({
          method: 'GET',
          url,
          onload: res => {
            try { resolve(JSON.parse(res.responseText)); }
            catch (e) { reject(new Error('Torn returned an unreadable response.')); }
          },
          onerror: () => reject(new Error('Network error talking to the Torn API.')),
          ontimeout: () => reject(new Error('Torn API request timed out.'))
        });
      });
    }
    return fetch(url, { method: 'GET', credentials: 'omit' }).then(res => res.json());
  }

  const money = value => '$' + Math.round(Number(value) || 0).toLocaleString('en-US');
  const points = value => Math.round(Number(value) || 0).toLocaleString('en-US') + ' points';
  const formatAmount = (value, kind) => (kind === 'points' ? points(value) : money(value));
  const normalizeName = value => String(value || '').trim().toLowerCase().replace(/[\s_]+/g, '');

  function parseAmount(raw) {
    const text = String(raw || '').trim().toLowerCase().replace(/[$,\s]/g, '');
    if (!text) return null;
    const match = text.match(/^(\d+(?:\.\d+)?)([kmb])?$/);
    if (!match) return null;
    const scale = { k: 1e3, m: 1e6, b: 1e9 }[match[2]] || 1;
    const value = Number(match[1]) * scale;
    return Number.isFinite(value) ? value : null;
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  /* ------------------------------------------------------------------ balances */

  function loadCache() {
    const cached = recall(CACHE_KEY, null);
    if (cached && cached.byId && Date.now() - Number(cached.fetchedAt || 0) < CACHE_TTL_MS * 10) {
      state.balances = cached.byId;
      state.fetchedAt = Number(cached.fetchedAt || 0);
    }
  }

  function fetchBalances(force) {
    const fresh = state.balances && Date.now() - state.fetchedAt < CACHE_TTL_MS;
    if (!force && fresh) return Promise.resolve(state.balances);
    if (state.fetching) return state.fetching;

    const key = apiKey();
    if (!key) {
      state.lastError = 'No API key set. Use the Tampermonkey menu -> Set Give Guard API key.';
      return Promise.reject(new Error(state.lastError));
    }

    const url = 'https://api.torn.com/faction/?selections=donations'
      + '&key=' + encodeURIComponent(key)
      + '&comment=TornIntel-GiveGuard';

    state.fetching = httpJson(url).then(data => {
      if (data && data.error) {
        throw new Error(data.error.error + ' (code ' + data.error.code + ')');
      }
      const byId = {};
      const donations = (data && data.donations) || {};
      Object.keys(donations).forEach(id => {
        const row = donations[id] || {};
        byId[String(id)] = {
          id: String(id),
          name: String(row.name || ''),
          money: Number(row.money_balance || 0),
          points: Number(row.points_balance || 0)
        };
      });
      state.balances = byId;
      state.fetchedAt = Date.now();
      state.lastError = null;
      store(CACHE_KEY, { fetchedAt: state.fetchedAt, byId });
      log('balances loaded', Object.keys(byId).length);
      return byId;
    }).catch(error => {
      state.lastError = error.message || String(error);
      throw error;
    }).finally(() => {
      state.fetching = null;
    });

    return state.fetching;
  }

  function refreshIfStale() {
    if (!apiEnabled() || Date.now() - state.fetchedAt < STALE_REFRESH_MS) return;
    fetchBalances(false).then(refreshAllChips).catch(refreshAllChips);
  }

  function lookupById(id) {
    return (state.balances && state.balances[String(id)]) || null;
  }

  function lookupByName(text) {
    const wanted = normalizeName(text);
    if (!wanted || !state.balances) return [];
    const rows = Object.values(state.balances);
    const exact = rows.filter(row => normalizeName(row.name) === wanted);
    if (exact.length) return exact;
    return rows.filter(row => normalizeName(row.name).indexOf(wanted) !== -1).slice(0, 6);
  }

  /* ------------------------------------------------------------------ DOM scan */

  function isVisible(el) {
    return Boolean(el && el.offsetParent !== null);
  }

  function fieldHint(el) {
    return [el.name, el.id, el.placeholder, el.className, el.getAttribute('aria-label'), el.getAttribute('data-testid')]
      .filter(Boolean).join(' ').toLowerCase();
  }

  function isValueInput(el) {
    if (!el || el.tagName !== 'INPUT' || el.disabled) return false;
    const type = String(el.getAttribute('type') || 'text').toLowerCase();
    if (NON_VALUE_INPUT_TYPES.indexOf(type) !== -1) return false;
    return !el.classList.contains('wai-btn');
  }

  function isAmountInput(el) {
    if (!isValueInput(el)) return false;
    if (el.classList.contains('input-money')) return true;
    return /amount|money|cash|sum|value|point/.test(fieldHint(el));
  }

  function isMemberInput(el) {
    if (!isValueInput(el)) return false;
    if (isAmountInput(el)) return false;
    return /user|member|name|recipient|player|search/.test(fieldHint(el));
  }

  // Torn wraps the whole page in a form, so only trust a form that sits inside the give block.
  function containerFor(el) {
    if (!el || !el.closest) return null;
    const scope = el.closest(GIVE_SCOPE_SELECTOR);
    const form = el.closest('form');
    if (form && (!scope || scope.contains(form))) return form;
    return scope || legacyContainerFor(el);
  }

  function legacyContainerFor(el) {
    let node = el;
    for (let depth = 0; node && depth < 8; depth += 1) {
      if (node.querySelector && findAmountInput(node)) return node;
      node = node.parentElement;
    }
    return null;
  }

  function memberScopeFor(container) {
    return container.closest(GIVE_SCOPE_SELECTOR) || container;
  }

  function findAmountInput(container) {
    return Array.from(container.querySelectorAll('input')).find(isAmountInput) || null;
  }

  function findMemberInput(container) {
    const inside = Array.from(container.querySelectorAll('input')).find(isMemberInput);
    if (inside) return inside;
    const scope = memberScopeFor(container);
    if (scope === container) return null;
    return Array.from(scope.querySelectorAll('input')).find(isMemberInput) || null;
  }

  // Torn renders "<name>`s current balance is $x" in the give block once a member is picked.
  function readPageBalance(container) {
    const scope = memberScopeFor(container);
    for (const el of scope.querySelectorAll('span, p, div, b, strong')) {
      if (el.children.length) continue;
      const raw = String(el.textContent || '').trim();
      if (raw.length > 120 || !/current balance is/i.test(raw)) continue;
      const match = raw.match(BALANCE_TEXT_RE);
      if (!match) continue;
      const value = Number(match[2].replace(/,/g, ''));
      if (!Number.isFinite(value)) continue;
      return { name: match[1].trim(), value, kind: raw.indexOf('$') === -1 ? 'points' : 'money' };
    }
    return null;
  }

  function transferKind(container) {
    const amountInput = findAmountInput(container);
    const hint = amountInput ? fieldHint(amountInput) : '';
    if (/point/.test(hint)) return 'points';
    const text = String(container.textContent || '').toLowerCase();
    if (/point/.test(text) && !/money|cash|\$/.test(text)) return 'points';
    return 'money';
  }

  function resolveMember(container) {
    // Only a link inside this form describes the selected member; the block also lists other members.
    const link = container.querySelector('a[href*="XID=" i]');
    if (link) {
      const match = link.href.match(/[?&]XID=(\d+)/i);
      if (match) {
        const row = lookupById(match[1]);
        if (row) return { row, matches: [row], typed: row.name };
      }
    }

    const hidden = container.querySelector('input[type="hidden"][name*="user" i], input[type="hidden"][name*="member" i], input[type="hidden"][id*="user" i]');
    if (hidden && /^\d+$/.test(String(hidden.value || '').trim())) {
      const row = lookupById(hidden.value.trim());
      if (row) return { row, matches: [row], typed: row.name };
    }

    const memberInput = findMemberInput(container);
    const typed = memberInput ? String(memberInput.value || '').trim() : '';
    if (!typed) return { row: null, matches: [], typed: '' };

    const bracket = typed.match(/\[(\d+)\]/);
    if (bracket) {
      const row = lookupById(bracket[1]);
      if (row) return { row, matches: [row], typed };
    }
    if (/^\d+$/.test(typed)) {
      const row = lookupById(typed);
      if (row) return { row, matches: [row], typed };
    }

    const matches = lookupByName(typed.replace(/\[\d+\]/, ''));
    return { row: matches.length === 1 ? matches[0] : null, matches, typed };
  }

  function evaluate(container) {
    const amountInput = findAmountInput(container);
    if (!amountInput) return null;

    const page = readPageBalance(container);
    const kind = page ? page.kind : transferKind(container);
    const amount = parseAmount(amountInput.value);
    const resolved = resolveMember(container);
    const apiBalance = resolved.row ? (kind === 'points' ? resolved.row.points : resolved.row.money) : null;
    const balance = page ? page.value : apiBalance;
    const name = (page && page.name) || (resolved.row && resolved.row.name) || resolved.typed || '';
    const available = balance === null ? null : Math.max(balance, 0);

    return {
      container,
      amountInput,
      kind,
      amount,
      resolved,
      name,
      balance,
      available,
      source: page ? 'page' : (apiBalance !== null ? 'api' : null),
      over: available !== null && amount !== null && amount > available
    };
  }

  /* ------------------------------------------------------------------ chip UI */

  // The give form is a flex row, so the chip goes after it and claims a full line of the parent.
  function placeChip(container, chip) {
    const parent = container.parentElement;
    if (!parent) {
      container.appendChild(chip);
      return;
    }
    container.insertAdjacentElement('afterend', chip);
    let display = '';
    try { display = window.getComputedStyle(parent).display || ''; } catch (e) { /* ignore */ }
    if (display.indexOf('flex') !== -1) {
      chip.style.flex = '1 1 100%';
      chip.style.width = '100%';
    } else if (display.indexOf('grid') !== -1) {
      chip.style.gridColumn = '1 / -1';
    }
  }

  function chipFor(container) {
    const existing = state.chips.get(container);
    if (existing && existing.isConnected) return existing;

    const chip = document.createElement('div');
    chip.className = CHIP_CLASS;
    placeChip(container, chip);
    state.chips.set(container, chip);
    return chip;
  }

  function renderChip(container) {
    const check = evaluate(container);
    if (!check) return;

    const { resolved, kind, amount, balance, available, name } = check;
    let cls = 'tfgg-muted';
    let html;

    if (balance === null) {
      if (resolved.matches && resolved.matches.length > 1) {
        const names = resolved.matches.map(row => escapeHtml(row.name) + ' &mdash; ' + formatAmount(kind === 'points' ? row.points : row.money, kind));
        html = '<b>Give Guard</b> ' + resolved.matches.length + ' matches:<br>' + names.join('<br>');
      } else if (resolved.typed) {
        html = '<b>Give Guard</b> No balance shown for &quot;' + escapeHtml(resolved.typed) + '&quot; yet.';
      } else {
        html = '<b>Give Guard</b> Pick a member to see their available balance.';
      }
    } else {
      const who = name ? escapeHtml(name) : 'This member';
      const head = available > 0
        ? who + ' has <b>' + formatAmount(available, kind) + '</b> available'
        : who + ' has <b>nothing</b> available (balance ' + formatAmount(balance, kind) + ')';

      if (amount === null) {
        cls = available > 0 ? 'tfgg-ok' : 'tfgg-warn';
        html = head + '.';
      } else if (amount > available) {
        cls = 'tfgg-warn';
        html = head + '.<br>Giving <b>' + formatAmount(amount, kind) + '</b> puts them '
          + formatAmount(amount - available, kind) + ' beyond it.';
      } else {
        cls = 'tfgg-ok';
        html = head + '.<br>Leaves ' + formatAmount(available - amount, kind) + ' after this transfer.';
      }
    }

    const chip = chipFor(container);
    if (chip.dataset.render === cls + '|' + html) return;
    chip.dataset.render = cls + '|' + html;
    chip.className = CHIP_CLASS + ' ' + cls;
    chip.innerHTML = html;
  }

  function refreshAllChips() {
    state.containers = state.containers.filter(container => container.isConnected);
    state.containers.forEach(renderChip);
  }

  /* ------------------------------------------------------------------ guard */

  function looksLikeSubmit(el) {
    if (!el) return false;
    const type = String((el.getAttribute && el.getAttribute('type')) || '').toLowerCase();
    if (el.tagName === 'INPUT' && type === 'submit') return true;
    const text = String(el.textContent || el.value || '').trim().toLowerCase();
    if (/^(give|send|confirm|submit|donate|transfer|pay)\b/.test(text)) return true;
    return text.length > 0 && /torn-btn/.test(String(el.className || '').toLowerCase());
  }

  function setAmount(amountInput, value) {
    amountInput.value = value === null ? '' : String(Math.floor(value));
    amountInput.dispatchEvent(new Event('input', { bubbles: true }));
    amountInput.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function replay(target) {
    state.bypass = target;
    target.click();
    setTimeout(() => { if (state.bypass === target) state.bypass = null; }, 0);
  }

  function isOwnUi(el) {
    return Boolean(el && el.closest && el.closest('#' + MODAL_ID + ', .' + CHIP_CLASS));
  }

  function guardClick(event) {
    if (!enforceEnabled()) return;
    if (isOwnUi(event.target)) return;
    const closest = event.target && event.target.closest ? event.target.closest.bind(event.target) : null;
    if (!closest) return;

    const maxButton = closest(MAX_BUTTON_SELECTOR);
    if (maxButton) {
      guardMaxButton(event, maxButton);
      return;
    }

    const target = closest('button, input[type="submit"], input[type="button"], a, .torn-btn');
    if (!target || !looksLikeSubmit(target)) return;
    if (state.bypass === target) return;

    const container = containerFor(target);
    if (!container) return;

    const check = evaluate(container);
    if (!check || check.amount === null) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    confirmTransfer(check, () => replay(target));
  }

  function guardMaxButton(event, maxButton) {
    const button = maxButton.tagName === 'INPUT' ? maxButton : maxButton.querySelector('input.wai-btn');
    if (!button || state.bypass === button) return;

    const container = containerFor(maxButton);
    if (!container) return;

    const check = evaluate(container);
    if (!check || check.balance !== null) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    openDialog({
      title: 'Warning',
      tone: 'warn',
      body: '<p>You clicked the shortcut that fills in <b>all faction funds</b>, but no member is selected yet.</p>'
        + '<p>Please recheck your work. Do you want to continue?</p>',
      buttons: [
        { label: 'No, clear the amount', kind: 'cancel', onClick: () => setAmount(check.amountInput, null) },
        { label: 'Yes, continue', kind: 'danger', onClick: () => replay(button) }
      ]
    });
  }

  function guardKey(event) {
    if (event.key !== 'Enter') return;
    const el = event.target;
    if (!enforceEnabled() || !el || isOwnUi(el) || !isAmountInput(el)) return;

    const container = containerFor(el);
    if (!container) return;
    const check = evaluate(container);
    if (!check || check.amount === null) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    confirmTransfer(check, () => {
      const submit = Array.from(container.querySelectorAll('button, input[type="submit"], input[type="button"], a, .torn-btn'))
        .find(node => !node.classList.contains('wai-btn') && looksLikeSubmit(node));
      if (submit) replay(submit);
      else if (el.form && typeof el.form.requestSubmit === 'function') el.form.requestSubmit();
    });
  }

  function confirmTransfer(check, proceed) {
    const who = escapeHtml(check.name || 'this member');
    const amountText = formatAmount(check.amount, check.kind);

    if (!check.name) {
      openDialog({
        title: 'Warning',
        tone: 'warn',
        body: '<p>No member is selected, but the amount is set to <b>' + amountText + '</b>.</p>'
          + '<p>Please recheck your work. Do you want to continue?</p>',
        buttons: [
          { label: 'No, go back', kind: 'cancel' },
          { label: 'Yes, continue', kind: 'danger', onClick: proceed }
        ]
      });
      return;
    }

    if (check.over) {
      const buttons = [{ label: 'No, go back', kind: 'cancel' }];
      if (check.available > 0) {
        buttons.push({
          label: 'Use ' + formatAmount(check.available, check.kind),
          kind: 'fill',
          onClick: () => { setAmount(check.amountInput, check.available); renderChip(check.container); }
        });
      }
      buttons.push({ label: 'Give anyway', kind: 'danger', onClick: proceed });

      openDialog({
        title: 'Balance check',
        tone: 'warn',
        body: '<p><b>' + who + '</b> has <b>' + formatAmount(check.available, check.kind) + '</b> available'
            + (check.balance < 0 ? ' (current balance ' + formatAmount(check.balance, check.kind) + ').' : '.') + '</p>'
          + '<p>You are giving <b>' + amountText + '</b>, which is <b>'
          + formatAmount(check.amount - check.available, check.kind) + '</b> more than that.</p>',
        buttons
      });
      return;
    }

    openDialog({
      title: 'Confirm transfer',
      tone: 'ok',
      body: '<p>Give <b>' + amountText + '</b> to <b>' + who + '</b>?</p>'
        + (check.balance === null ? ''
          : '<p>Available ' + formatAmount(check.available, check.kind)
            + ', leaving ' + formatAmount(check.available - check.amount, check.kind) + ' afterwards.</p>'),
      buttons: [
        { label: 'No, go back', kind: 'cancel' },
        { label: 'Yes, give ' + amountText, kind: 'confirm', onClick: proceed }
      ]
    });
  }

  function closeModal() {
    const existing = document.getElementById(MODAL_ID);
    if (existing) existing.remove();
  }

  function openDialog(options) {
    closeModal();
    const overlay = document.createElement('div');
    overlay.id = MODAL_ID;
    overlay.dataset.tone = options.tone || 'warn';

    const card = document.createElement('div');
    card.className = 'tfgg-modal-card';
    card.setAttribute('role', 'alertdialog');
    card.setAttribute('aria-modal', 'true');
    card.innerHTML = '<div class="tfgg-modal-title"></div><div class="tfgg-modal-body"></div><div class="tfgg-modal-actions"></div>';
    card.querySelector('.tfgg-modal-title').textContent = options.title;
    card.querySelector('.tfgg-modal-body').innerHTML = options.body;

    const actions = card.querySelector('.tfgg-modal-actions');
    options.buttons.forEach(spec => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'tfgg-btn tfgg-btn-' + (spec.kind || 'cancel');
      button.textContent = spec.label;
      button.addEventListener('click', () => {
        closeModal();
        if (spec.onClick) spec.onClick();
      });
      actions.appendChild(button);
    });

    overlay.appendChild(card);
    overlay.addEventListener('click', event => {
      if (event.target === overlay) closeModal();
    });
    document.body.appendChild(overlay);

    const first = card.querySelector('.tfgg-btn');
    if (first) first.focus();
  }

  /* ------------------------------------------------------------------ wiring */

  function attach() {
    const amountInputs = Array.from(document.querySelectorAll('input')).filter(el => isAmountInput(el) && isVisible(el));
    amountInputs.forEach(amountInput => {
      const container = containerFor(amountInput);
      if (!container || state.watched.has(container)) return;
      const inGiveScope = Boolean(amountInput.closest(GIVE_SCOPE_SELECTOR));
      if (!inGiveScope && !findMemberInput(container) && !container.querySelector('a[href*="XID=" i]')) return;
      state.watched.add(container);
      state.containers.push(container);

      const rerender = () => renderChip(container);
      container.addEventListener('input', rerender);
      container.addEventListener('change', rerender);
      container.addEventListener('click', () => setTimeout(rerender, 60));
      const scope = memberScopeFor(container);
      if (scope !== container) scope.addEventListener('input', rerender);

      refreshIfStale();
      rerender();
      log('watching give form', container);
    });
  }

  function scheduleScan() {
    if (state.rescanTimer) return;
    state.rescanTimer = setTimeout(() => {
      state.rescanTimer = null;
      attach();
    }, 200);
  }

  addStyle(`
    .${CHIP_CLASS} {
      display: block; width: 100%; max-width: 100%; min-width: 0;
      box-sizing: border-box; float: none; clear: both;
      margin: 8px 0 4px; padding: 7px 10px; border-radius: 5px;
      font: ${IS_TORN_PDA ? '13px' : '12px'}/1.45 Arial, sans-serif;
      background: rgba(0,0,0,0.78); color: #eee; border-left: 3px solid #888;
      white-space: normal; overflow-wrap: break-word; text-align: left;
    }
    .${CHIP_CLASS} b { color: #fff; white-space: nowrap; }
    .${CHIP_CLASS}.tfgg-ok { border-left-color: #4caf50; }
    .${CHIP_CLASS}.tfgg-warn { border-left-color: #e53935; background: rgba(120,20,20,0.85); }
    .${CHIP_CLASS}.tfgg-muted { border-left-color: #666; color: #bbb; }
    #${MODAL_ID} {
      position: fixed; inset: 0; z-index: 2147483647; display: flex;
      align-items: center; justify-content: center; padding: 16px;
      background: rgba(0,0,0,0.62);
    }
    #${MODAL_ID} .tfgg-modal-card {
      width: min(420px, 100%); box-sizing: border-box; background: #1b1b1b; color: #eee;
      border: 1px solid #555; border-radius: 8px; padding: 14px;
      font: 13px/1.5 Arial, sans-serif; box-shadow: 0 8px 30px rgba(0,0,0,0.6);
      max-height: calc(100dvh - 32px); overflow-y: auto;
    }
    #${MODAL_ID} .tfgg-modal-title { font-size: 15px; font-weight: bold; color: #e53935; margin-bottom: 8px; }
    #${MODAL_ID}[data-tone="ok"] .tfgg-modal-title { color: #8bc34a; }
    #${MODAL_ID} .tfgg-modal-body p { margin: 0 0 8px; }
    #${MODAL_ID} .tfgg-modal-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    #${MODAL_ID} .tfgg-btn {
      flex: 1 1 auto; min-width: 110px; min-height: ${IS_TORN_PDA ? '44px' : '34px'};
      border-radius: 5px; border: 1px solid #555; background: #2b2b2b; color: #eee;
      font: inherit; cursor: pointer; padding: 6px 10px;
    }
    #${MODAL_ID} .tfgg-btn-confirm { border-color: #4caf50; color: #b7e2b9; }
    #${MODAL_ID} .tfgg-btn-fill { border-color: #4caf50; color: #b7e2b9; }
    #${MODAL_ID} .tfgg-btn-danger { border-color: #e53935; color: #ffb4b1; }
  `);

  registerMenuCommand('Set Give Guard API key', () => {
    const current = String(recall(API_KEY_KEY, '') || '');
    const next = prompt('Torn API key with faction access (needs the donations selection):', current);
    if (next === null) return;
    store(API_KEY_KEY, next.trim());
    store(API_ENABLED_KEY, Boolean(next.trim()));
    fetchBalances(true).then(refreshAllChips).catch(refreshAllChips);
  });

  registerMenuCommand('Toggle optional API fallback', () => {
    const next = !apiEnabled();
    store(API_ENABLED_KEY, next);
    if (next) {
      fetchBalances(true).then(refreshAllChips).catch(refreshAllChips);
    } else {
      refreshAllChips();
      alert('Give Guard will now use only the balance shown on the faction page.');
    }
  });

  registerMenuCommand('Refresh vault balances', () => {
    if (!apiEnabled()) {
      alert('API fallback is disabled. Give Guard is using the balance shown on the faction page.');
      return;
    }
    fetchBalances(true)
      .then(byId => { refreshAllChips(); alert('Give Guard loaded ' + Object.keys(byId).length + ' member balances.'); })
      .catch(error => { refreshAllChips(); alert('Give Guard could not load balances: ' + (error.message || error)); });
  });

  registerMenuCommand('Toggle blocking over-balance gives', () => {
    const next = !enforceEnabled();
    store(ENFORCE_KEY, next);
    alert('Give Guard will now ' + (next ? 'block and confirm' : 'only warn about') + ' gives above a member balance.');
  });

  registerMenuCommand('Toggle Give Guard debug logging', () => {
    store(DEBUG_KEY, !debugEnabled());
  });

  registerMenuCommand('Copy give form HTML (for troubleshooting)', () => {
    state.containers = state.containers.filter(container => container.isConnected);
    const text = state.containers.length
      ? state.containers.map((container, index) =>
          '--- container ' + (index + 1) + ': ' + container.tagName + '.' + (container.className || '(no class)') + ' ---\n'
          + container.outerHTML).join('\n\n')
      : 'No give form detected on this page.';
    const done = () => alert('Give Guard copied ' + state.containers.length + ' container(s) to the clipboard.');
    const fallback = () => { console.log(text); alert('Clipboard blocked. The HTML was logged to the console instead.'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, fallback);
    } else {
      fallback();
    }
  });

  document.addEventListener('click', guardClick, true);
  document.addEventListener('keydown', guardKey, true);
  window.addEventListener('hashchange', scheduleScan);

  if (apiEnabled()) loadCache();

  new MutationObserver(scheduleScan).observe(document.documentElement, { childList: true, subtree: true });
  setInterval(() => { attach(); refreshAllChips(); }, RESCAN_MS);
  attach();

  console.info('[Give Guard] v' + VERSION + ' loaded (' + (IS_TORN_PDA ? 'PDA/touch' : 'desktop') + ').');
})();
