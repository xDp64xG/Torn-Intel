// ==UserScript==
// @name         TornIntel Bank Request
// @namespace    http://tampermonkey.net/
// @version      0.6.0
// @description  Request money from the faction vault; posts to the TornIntel Discord bot with a prefilled fulfill link.
// @author       TornIntel
// @match        https://www.torn.com/*
// @match        https://torn.com/*
// @connect      *
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_notification
// @homepageURL  https://github.com/xDp64xG/Torn-Intel
// @supportURL   https://github.com/xDp64xG/Torn-Intel/issues
// @updateURL    https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/bank_request.user.js
// @downloadURL  https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/bank_request.user.js
// ==/UserScript==

(() => {
    'use strict';

    const DEFAULT_BASE_URLS = ['http://127.0.0.1:8765', 'http://localhost:8765'];
    const DISCOVERY_URL = 'https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/revive_request_endpoint.json';
    const OVERRIDE_KEY = 'tornintel_bank_listener_override';
    const BUTTON_POSITION_KEY = 'tornintel_bank_button_position';
    const BUTTON_ID = 'tornintel-bank-btn';
    const MODAL_ID = 'tornintel-bank-modal';
    const MENU_ITEM_ID = 'tornintel-bank-menu-item';
    const TOAST_ID = 'tornintel-bank-toast';
    const FLOATING_BUTTON_KEY = 'tornintel_bank_floating_button';
    const NOTIFY_POLL_MS = 30000;
    const MAX_AMOUNT = 1e12;

    const trimSlash = url => String(url || '').replace(/\/+$/, '');
    const isHttpUrl = url => /^https?:\/\/.+/i.test(String(url || ''));

    const getValue = (key, fallback = '') => {
        try { return typeof GM_getValue === 'function' ? GM_getValue(key, fallback) : fallback; } catch { return fallback; }
    };
    const setValue = (key, value) => {
        try { if (typeof GM_setValue === 'function') GM_setValue(key, value); } catch { /* ignore */ }
    };

    const request = (method, url, data = null, timeoutMs = 4000) => new Promise((resolve, reject) => {
        GM_xmlhttpRequest({
            method,
            url,
            headers: { 'Content-Type': 'application/json' },
            data: data ? JSON.stringify(data) : undefined,
            timeout: timeoutMs,
            onload: r => {
                let body = null;
                try { body = JSON.parse(r.responseText); } catch { body = null; }
                if (r.status >= 200 && r.status < 300) resolve(body || { ok: true });
                else reject(new Error(body?.error || `HTTP ${r.status}`));
            },
            ontimeout: () => reject(new Error('Listener timed out')),
            onerror: () => reject(new Error(`Request failed (${method} ${url})`))
        });
    });

    let activeBaseUrl = null;

    const resolveBaseUrl = async () => {
        if (activeBaseUrl) return activeBaseUrl;
        let discovered = [];
        try {
            const res = await request('GET', DISCOVERY_URL);
            discovered = [...(Array.isArray(res?.base_urls) ? res.base_urls : []), res?.base_url];
        } catch { /* discovery optional */ }

        const candidates = [...new Set([getValue(OVERRIDE_KEY, ''), ...discovered, ...DEFAULT_BASE_URLS]
            .map(trimSlash).filter(isHttpUrl))];

        for (const baseUrl of candidates) {
            try {
                const res = await request('GET', `${baseUrl}/health`, null, 2500);
                if (res?.ok) {
                    activeBaseUrl = baseUrl;
                    return baseUrl;
                }
            } catch { /* try next */ }
        }
        throw new Error(
            `No reachable TornIntel listener. Start it with: python main.py revive_listener serve --host 0.0.0.0 --port 8765. ` +
            `For an internet tunnel, refresh the ephemeral trycloudflare URL in scripts/tampermonkey/revive_request_endpoint.json. ` +
            `Tried: ${candidates.join(', ')}`
        );
    };

    if (typeof GM_registerMenuCommand === 'function') {
        GM_registerMenuCommand('TornIntel Bank: Set/Clear Listener URL', () => {
            const input = window.prompt('Listener URL override (blank = auto discovery):', getValue(OVERRIDE_KEY, ''));
            if (input === null) return;
            const url = trimSlash(input);
            if (url && !isHttpUrl(url)) {
                window.alert('Invalid URL. Example: http://192.168.1.50:8765');
                return;
            }
            setValue(OVERRIDE_KEY, url);
            activeBaseUrl = null;
        });
        GM_registerMenuCommand('TornIntel Bank: Toggle floating button', () => {
            setFloatingButton(!isFloatingButtonEnabled());
        });
    }

    // Name comes from the sidebar link: <a href="/profiles.php?XID=..." aria-label="Name: JeffBezas">JeffBezas</a>
    const getCurrentUser = () => {
        const link = document.querySelector('a[class*="menu-value"][href*="profiles.php?XID="][aria-label^="Name:"]')
            || document.querySelector('a[href*="profiles.php?XID="][aria-label^="Name:"]');
        if (link) {
            const name = (link.textContent || '').trim()
                || String(link.getAttribute('aria-label') || '').replace(/^Name:\s*/, '').trim();
            const id = link.getAttribute('href')?.match(/XID=(\d+)/)?.[1];
            if (name) return { name, id: id ? Number(id) : null };
        }
        try {
            const key = Object.keys(sessionStorage).find(k => /sidebarData\d+/.test(k));
            const user = key ? JSON.parse(sessionStorage.getItem(key))?.user : null;
            if (user?.name) return { name: String(user.name), id: user.userID ? Number(user.userID) : null };
        } catch { /* ignore */ }
        return { name: null, id: null };
    };

    // Accepts "1500000", "1,500,000", "1.5m", "250k", "2b", "all". The listener caps it to your vault balance.
    const parseAmount = (text) => {
        const cleaned = String(text || '').trim().toLowerCase().replace(/[,$\s]/g, '');
        if (cleaned === 'all' || cleaned === 'max') return 'all';
        const match = cleaned.match(/^(\d+(?:\.\d+)?)([kmb])?$/);
        if (!match) return null;
        const mult = { k: 1e3, m: 1e6, b: 1e9 }[match[2]] || 1;
        const value = Math.round(Number(match[1]) * mult);
        return Number.isFinite(value) && value > 0 && value <= MAX_AMOUNT ? value : null;
    };

    GM_addStyle(`
        #${BUTTON_ID} {
            position: fixed; left: 12px; bottom: calc(12px + env(safe-area-inset-bottom, 0px)); z-index: 2147483645;
            padding: 5px 10px; border: none; border-radius: 6px; cursor: grab; touch-action: none;
            background: #2e7d32; color: #fff; font-size: 12px; font-weight: 700;
            box-shadow: 0 4px 12px rgba(0,0,0,0.35);
        }
        #${MODAL_ID} {
            position: fixed; inset: 0; z-index: 2147483646; display: flex; align-items: center; justify-content: center;
            background: rgba(0,0,0,0.55);
        }
        #${MODAL_ID} .ti-bank-box {
            width: min(300px, calc(100vw - 32px)); padding: 14px; border-radius: 8px;
            background: #1f242b; color: #eef2f6; font-size: 13px; box-shadow: 0 12px 28px rgba(0,0,0,0.45);
        }
        #${MODAL_ID} .ti-bank-title { font-weight: 700; font-size: 14px; margin-bottom: 8px; }
        #${MODAL_ID} .ti-bank-name { margin-bottom: 10px; color: #b8c4d0; }
        #${MODAL_ID} input {
            width: 100%; box-sizing: border-box; padding: 7px 8px; border-radius: 4px;
            border: 1px solid #3a434e; background: #12161b; color: #fff; font-size: 13px;
        }
        #${MODAL_ID} .ti-bank-status { min-height: 16px; margin-top: 6px; font-size: 12px; }
        #${MODAL_ID} .ti-bank-status.err { color: #ff7b7b; }
        #${MODAL_ID} .ti-bank-status.ok { color: #6fdc8c; }
        #${MODAL_ID} .ti-bank-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
        #${MODAL_ID} button { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-weight: 700; color: #fff; }
        #${MODAL_ID} .ti-bank-cancel { background: #555e69; }
        #${MODAL_ID} .ti-bank-confirm { background: #2e7d32; }
        #${MODAL_ID} button:disabled { opacity: 0.6; cursor: default; }
        #${MODAL_ID} .ti-bank-option { display: flex; align-items: center; gap: 6px; margin-top: 10px; color: #b8c4d0; font-size: 12px; cursor: pointer; }
        #${MODAL_ID} .ti-bank-option input { width: auto; margin: 0; }
        #${TOAST_ID} {
            position: fixed; top: 12px; right: 12px; z-index: 2147483647; display: flex; flex-direction: column; gap: 8px;
            max-width: min(320px, calc(100vw - 24px));
        }
        #${TOAST_ID} .ti-bank-toast {
            padding: 10px 12px; border-radius: 6px; background: #1f242b; color: #eef2f6; font-size: 12px;
            border-left: 4px solid #e74c3c; box-shadow: 0 8px 20px rgba(0,0,0,0.45); cursor: pointer;
        }
        #${TOAST_ID} .ti-bank-toast strong { display: block; margin-bottom: 3px; font-size: 13px; }
    `);

    const closeModal = () => document.getElementById(MODAL_ID)?.remove();

    const openModal = () => {
        if (document.getElementById(MODAL_ID)) return;
        const user = getCurrentUser();

        const overlay = document.createElement('div');
        overlay.id = MODAL_ID;
        overlay.innerHTML = `
            <div class="ti-bank-box" role="dialog" aria-label="Bank request">
                <div class="ti-bank-title">Bank Request</div>
                <div class="ti-bank-name"></div>
                <input type="text" placeholder="Amount (e.g. 5000000, 5m or all)" autocomplete="off">
                <div class="ti-bank-status"></div>
                <label class="ti-bank-option"><input type="checkbox" class="ti-bank-floating"> Show floating draggable Bank button</label>
                <div class="ti-bank-actions">
                    <button type="button" class="ti-bank-cancel">Cancel</button>
                    <button type="button" class="ti-bank-confirm">Confirm</button>
                </div>
            </div>`;

        const nameEl = overlay.querySelector('.ti-bank-name');
        const input = overlay.querySelector('input[type="text"]');
        const floatingToggle = overlay.querySelector('.ti-bank-floating');
        const status = overlay.querySelector('.ti-bank-status');
        const cancelBtn = overlay.querySelector('.ti-bank-cancel');
        const confirmBtn = overlay.querySelector('.ti-bank-confirm');

        nameEl.textContent = user.name ? `Name: ${user.name}` : 'Name: (not found)';
        floatingToggle.checked = isFloatingButtonEnabled();
        floatingToggle.addEventListener('change', () => setFloatingButton(floatingToggle.checked));

        const setStatus = (text, kind = '') => {
            status.textContent = text;
            status.className = `ti-bank-status ${kind}`;
        };

        const submit = async () => {
            if (!user.name || !user.id) {
                setStatus('Could not find your name/ID on the page.', 'err');
                return;
            }
            const amount = parseAmount(input.value);
            if (!amount) {
                setStatus('Enter a valid amount (e.g. 5m or all).', 'err');
                return;
            }

            const amountLabel = amount === 'all' ? 'your full balance' : `$${amount.toLocaleString()}`;
            confirmBtn.disabled = true;
            cancelBtn.disabled = true;
            setStatus(`Checking balance and requesting ${amountLabel}...`);
            try {
                const baseUrl = await resolveBaseUrl();
                const res = await request('POST', `${baseUrl}/bank-request`, {
                    requester_name: user.name,
                    requester_id: user.id,
                    amount,
                    source: 'tampermonkey-bank',
                    notes: `Requested from ${window.location.pathname}`
                }, 20000);
                if (!res?.ok) throw new Error(res?.error || 'unknown_error');
                const granted = Number(res.request?.amount || 0);
                const capped = res.capped ? ' (capped to your vault balance)' : '';
                setStatus(`Requested $${granted.toLocaleString()} from ${res.faction_name || 'your faction'}${capped}.`, 'ok');
                window.setTimeout(closeModal, 2500);
            } catch (err) {
                activeBaseUrl = null;
                setStatus(err?.message || String(err), 'err');
                confirmBtn.disabled = false;
                cancelBtn.disabled = false;
            }
        };

        cancelBtn.addEventListener('click', closeModal);
        confirmBtn.addEventListener('click', submit);
        overlay.addEventListener('click', (e) => { if (e.target === overlay && !cancelBtn.disabled) closeModal(); });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submit();
            if (e.key === 'Escape' && !cancelBtn.disabled) closeModal();
        });

        document.body.appendChild(overlay);
        input.focus();
    };

    const mountButton = () => {
        if (!document.body || document.getElementById(BUTTON_ID)) return;
        const btn = document.createElement('button');
        btn.id = BUTTON_ID;
        btn.type = 'button';
        btn.textContent = 'Bank';
        let pointerStart = null;
        let dragged = false;
        const savedPosition = getValue(BUTTON_POSITION_KEY, null);
        if (savedPosition && Number.isFinite(savedPosition.left) && Number.isFinite(savedPosition.top)) {
            btn.style.left = `${savedPosition.left}px`;
            btn.style.top = `${savedPosition.top}px`;
            btn.style.bottom = 'auto';
        }
        btn.addEventListener('pointerdown', event => {
            if (event.button !== 0) return;
            pointerStart = {
                pointerId: event.pointerId,
                x: event.clientX,
                y: event.clientY,
                left: btn.getBoundingClientRect().left,
                top: btn.getBoundingClientRect().top
            };
            dragged = false;
            btn.setPointerCapture(event.pointerId);
        });
        btn.addEventListener('pointermove', event => {
            if (!pointerStart || pointerStart.pointerId !== event.pointerId) return;
            const deltaX = event.clientX - pointerStart.x;
            const deltaY = event.clientY - pointerStart.y;
            if (!dragged && Math.hypot(deltaX, deltaY) < 5) return;
            dragged = true;
            const left = Math.max(0, Math.min(window.innerWidth - btn.offsetWidth, pointerStart.left + deltaX));
            const top = Math.max(0, Math.min(window.innerHeight - btn.offsetHeight, pointerStart.top + deltaY));
            btn.style.left = `${left}px`;
            btn.style.top = `${top}px`;
            btn.style.bottom = 'auto';
            btn.style.cursor = 'grabbing';
        });
        const stopDragging = event => {
            if (!pointerStart || pointerStart.pointerId !== event.pointerId) return;
            if (dragged) {
                const bounds = btn.getBoundingClientRect();
                setValue(BUTTON_POSITION_KEY, { left: bounds.left, top: bounds.top });
            }
            pointerStart = null;
            btn.style.cursor = 'grab';
        };
        btn.addEventListener('pointerup', stopDragging);
        btn.addEventListener('pointercancel', stopDragging);
        btn.addEventListener('click', event => {
            if (dragged) {
                event.preventDefault();
                dragged = false;
                return;
            }
            openModal();
        });
        document.body.appendChild(btn);
    };

    function isFloatingButtonEnabled() {
        return getValue(FLOATING_BUTTON_KEY, false) === true;
    }

    function setFloatingButton(enabled) {
        setValue(FLOATING_BUTTON_KEY, Boolean(enabled));
        syncFloatingButton();
    }

    function syncFloatingButton() {
        if (isFloatingButtonEnabled()) mountButton();
        else document.getElementById(BUTTON_ID)?.remove();
    }

    // Adds a "Bank Request" entry to Torn's profile dropdown (ul.settings-menu), like Scouter Target Finder.
    const injectMenuItem = () => {
        const menu = document.querySelector('ul.settings-menu');
        if (!menu || document.getElementById(MENU_ITEM_ID)) return;

        const li = document.createElement('li');
        li.id = MENU_ITEM_ID;
        li.className = 'setting tornintel-bank-item';
        li.innerHTML = `
            <label class="setting-container" style="cursor:pointer">
                <div class="icon-wrapper">
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M11.8 10.9c-2.27-.59-3-1.2-3-2.15 0-1.09 1.01-1.85 2.7-1.85 1.78 0 2.44.85 2.5 2.1h2.21c-.07-1.72-1.12-3.3-3.21-3.81V3h-3v2.16c-1.94.42-3.5 1.68-3.5 3.61 0 2.31 1.91 3.46 4.7 4.13 2.5.6 3 1.48 3 2.41 0 .69-.49 1.79-2.7 1.79-2.06 0-2.87-.92-2.98-2.1h-2.2c.12 2.19 1.76 3.42 3.68 3.83V21h3v-2.15c1.95-.37 3.5-1.5 3.5-3.55 0-2.84-2.43-3.81-4.7-4.4z"/></svg>
                </div>
                <span class="setting-name">Bank Request</span>
            </label>`;

        const settingsLink = menu.querySelector('li.link a[href="/preferences.php"]');
        const logoutLink = menu.querySelector('li.link a[href^="/logout.php"]');
        const anchor = settingsLink?.parentElement || logoutLink?.parentElement;
        if (anchor) menu.insertBefore(li, anchor);
        else menu.appendChild(li);

        li.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            openModal();
        });
    };

    const showToast = (title, text) => {
        let container = document.getElementById(TOAST_ID);
        if (!container) {
            container = document.createElement('div');
            container.id = TOAST_ID;
            document.body.appendChild(container);
        }
        const toast = document.createElement('div');
        toast.className = 'ti-bank-toast';
        const heading = document.createElement('strong');
        heading.textContent = title;
        const body = document.createElement('div');
        body.textContent = text;
        toast.append(heading, body);
        toast.addEventListener('click', () => toast.remove());
        container.appendChild(toast);
        window.setTimeout(() => toast.remove(), 20000);

        if (typeof GM_notification === 'function') {
            try { GM_notification({ title, text, timeout: 20000 }); } catch { /* optional */ }
        }
    };

    const describeNotification = (row) => {
        const amount = `$${Number(row.amount || 0).toLocaleString()}`;
        const reason = String(row.resolution_note || '').trim();
        if (row.status === 'expired') {
            return ['Bank request expired', `Your request for ${amount} wasn't fulfilled within 1 hour.`];
        }
        const by = row.resolved_by ? ` by ${row.resolved_by}` : '';
        return ['Bank request cancelled', `Your request for ${amount} was cancelled${by}.${reason ? ` Reason: ${reason}` : ''}`];
    };

    let notifyTimer = null;
    const pollNotifications = async () => {
        let delay = NOTIFY_POLL_MS;
        try {
            const user = getCurrentUser();
            if (user.id) {
                const baseUrl = await resolveBaseUrl();
                const res = await request('GET', `${baseUrl}/bank-request/notifications?requester_id=${encodeURIComponent(user.id)}`);
                for (const row of Array.isArray(res?.notifications) ? res.notifications : []) {
                    const [title, text] = describeNotification(row);
                    showToast(title, text);
                }
            }
        } catch {
            activeBaseUrl = null;
            delay = NOTIFY_POLL_MS * 4;
        }
        notifyTimer = window.setTimeout(pollNotifications, delay);
    };

    new MutationObserver(injectMenuItem).observe(document.body, { childList: true, subtree: true });
    injectMenuItem();
    syncFloatingButton();
    window.setInterval(syncFloatingButton, 5000);
    if (!notifyTimer) pollNotifications();
})();
