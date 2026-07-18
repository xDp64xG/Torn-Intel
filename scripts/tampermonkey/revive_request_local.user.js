// ==UserScript==
// @name         TornIntel Local Revive Request
// @namespace    http://tampermonkey.net/
// @version      0.4.17
// @description  Send local revive requests into TornIntel over a local HTTP listener.
// @author       TornIntel
// @match        https://www.torn.com/*
// @match        https://torn.com/*
// @connect      *
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @homepageURL  https://github.com/xDp64xG/Torn-Intel
// @supportURL   https://github.com/xDp64xG/Torn-Intel/issues
// Ping 
// @updateURL    https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/revive_request_local.user.js
// @downloadURL  https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/revive_request_local.user.js
// ==/UserScript==

(() => {
    'use strict';

    const DEFAULT_BASE_URLS = [
        'http://127.0.0.1:8765',
        'http://localhost:8765'
    ];
    const DISCOVERY_URL = 'https://raw.githubusercontent.com/xDp64xG/Torn-Intel/main/scripts/tampermonkey/revive_request_endpoint.json';
    const BASE_URL_KEY = 'tornintel_revive_listener_base_url_override';
    const DISCOVERED_BASE_URL_KEY = 'tornintel_revive_listener_base_url_discovered';
    const DISCOVERED_BASE_URLS_KEY = 'tornintel_revive_listener_base_urls_discovered';
    const DISCOVERED_BASE_URL_AT_KEY = 'tornintel_revive_listener_base_url_discovered_at';
    const DISCOVERY_CACHE_MS = 5 * 60 * 1000;
    const NOTIFICATION_POLL_MS = 15000;
    const NOTICE_DURATION_MS = 25000;
    const BUTTON_ID = 'tornintel-local-revive-btn';
    const ICON_ID = 'tornintel-local-revive-icon';
    const PDA_BAR_BUTTON_ID = 'tornintel-local-revive-pda-bar-btn';
    const DEBUG_BADGE_ID = 'tornintel-local-revive-debug';
    const ICON_POS_KEY = 'tornintel_local_revive_icon_position_v2';
    const BUTTON_RECHECK_MS = 2000;
    const ICON_DRAG_THRESHOLD = 8;
    const DEBUG_DIAGNOSTIC_DELAY_MS = 8000;

    const trimSlash = url => String(url || '').replace(/\/+$/, '');
    const isHttpUrl = url => /^https?:\/\/.+/i.test(String(url || ''));
    const unique = values => [...new Set(values.filter(Boolean))];
    const normalizeUrls = values => unique((Array.isArray(values) ? values : [values]).map(trimSlash).filter(isHttpUrl));
    const isLocalFallbackUrl = url => /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/i.test(trimSlash(url));

    const state = {
        activeBaseUrl: null,
        discoveryPromise: null,
        notificationTimer: null,
        lastCandidates: [],
        buttonObserverStarted: false,
        buttonRecheckTimer: null,
        iconDragging: false,
        lastError: null,
        bootedAt: Date.now(),
        debugPopupShown: false,
        mountPasses: 0
    };

    const debugLog = (message, popup = false) => {
        const line = `[TornIntel][debug] ${message}`;
        console.info(line);
        if (popup) {
            showNotice(`DEBUG\n${message}`, 'error', 30000);
        }
    };

    const hasVisibleControl = () => {
        return Boolean(
            document.getElementById(BUTTON_ID) ||
            document.getElementById(PDA_BAR_BUTTON_ID) ||
            document.getElementById(ICON_ID)
        );
    };

    const gmGetValue = (key, fallback = '') => {
        try {
            if (typeof GM_getValue === 'function') {
                return GM_getValue(key, fallback);
            }
            const raw = window.localStorage.getItem(`ti:${key}`);
            return raw === null ? fallback : raw;
        } catch {
            return fallback;
        }
    };

    const gmSetValue = (key, value) => {
        try {
            if (typeof GM_setValue === 'function') {
                GM_setValue(key, value);
                return;
            }
            window.localStorage.setItem(`ti:${key}`, String(value));
        } catch {
            // Best effort fallback only.
        }
    };

    const gmAddStyleSafe = (cssText) => {
        if (!cssText) return;
        try {
            if (typeof GM_addStyle === 'function') {
                GM_addStyle(cssText);
                return;
            }
        } catch {
            // Fall through to DOM style injection.
        }

        const style = document.createElement('style');
        style.type = 'text/css';
        style.textContent = String(cssText);
        (document.head || document.documentElement || document.body).appendChild(style);
    };

    const gmRegisterMenuCommandSafe = (label, handler) => {
        try {
            if (typeof GM_registerMenuCommand === 'function') {
                GM_registerMenuCommand(label, handler);
                return true;
            }
        } catch {
            // Ignore unsupported manager APIs.
        }
        return false;
    };

    const getOverrideBaseUrl = () => trimSlash(gmGetValue(BASE_URL_KEY, ''));
    const setOverrideBaseUrl = url => gmSetValue(BASE_URL_KEY, trimSlash(url));

    const endpoint = (baseUrl, path) => `${trimSlash(baseUrl)}${path}`;

    const ensureNoticeStyles = () => {
        if (document.getElementById('tornintel-revive-notice-style')) return;
        gmAddStyleSafe(`
            #tornintel-revive-notice-style {}
            .tornintel-revive-notice-stack {
                position: fixed;
                right: 16px;
                bottom: 16px;
                z-index: 2147483647;
                display: flex;
                flex-direction: column;
                gap: 8px;
                width: min(420px, calc(100vw - 24px));
                pointer-events: none;
            }
            .tornintel-revive-notice {
                pointer-events: auto;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-left-width: 4px;
                border-radius: 8px;
                background: rgba(19, 24, 31, 0.96);
                color: #f3f7fb;
                box-shadow: 0 12px 28px rgba(0, 0, 0, 0.35);
                padding: 10px 12px;
                font-size: 13px;
                line-height: 1.35;
                white-space: pre-line;
                opacity: 0;
                transform: translateY(8px);
                transition: opacity 180ms ease, transform 180ms ease;
            }
            .tornintel-revive-notice.is-visible {
                opacity: 1;
                transform: translateY(0);
            }
            .tornintel-revive-notice--info { border-left-color: #4ea1ff; }
            .tornintel-revive-notice--success { border-left-color: #39d98a; }
            .tornintel-revive-notice--error { border-left-color: #ff6b6b; }
        `);
        const styleTag = document.createElement('style');
        styleTag.id = 'tornintel-revive-notice-style';
        styleTag.textContent = '';
        document.head.appendChild(styleTag);
    };

    const getNoticeStack = () => {
        ensureNoticeStyles();
        let stack = document.getElementById('tornintel-revive-notice-stack');
        if (!stack) {
            stack = document.createElement('div');
            stack.id = 'tornintel-revive-notice-stack';
            stack.className = 'tornintel-revive-notice-stack';
            document.body.appendChild(stack);
        }
        return stack;
    };

    const showNotice = (message, kind = 'info', durationMs = NOTICE_DURATION_MS) => {
        if (!message) return;
        const stack = getNoticeStack();
        const notice = document.createElement('div');
        notice.className = `tornintel-revive-notice tornintel-revive-notice--${kind}`;
        notice.textContent = String(message);
        stack.appendChild(notice);

        requestAnimationFrame(() => {
            notice.classList.add('is-visible');
        });

        window.setTimeout(() => {
            notice.classList.remove('is-visible');
            window.setTimeout(() => {
                notice.remove();
            }, 220);
        }, Math.max(20000, Number(durationMs) || NOTICE_DURATION_MS));
    };

    const formatError = (err) => {
        if (!err) return 'unknown_error';
        const name = err?.name ? String(err.name) : 'Error';
        const msg = err?.message ? String(err.message) : String(err);
        return `${name}: ${msg}`;
    };

    const collectDiagnostics = () => {
        const lines = [
            'TornIntel mobile diagnostics',
            `URL: ${window.location.href}`,
            `UA: ${navigator.userAgent}`,
            `Viewport: ${window.innerWidth}x${window.innerHeight}`,
            `Body ready: ${Boolean(document.body)}`,
            `Mobile mode: ${isMobileClient()}`,
            `Button exists: ${Boolean(document.getElementById(BUTTON_ID))}`,
            `Icon exists: ${Boolean(document.getElementById(ICON_ID))}`,
            `PDA bar button exists: ${Boolean(document.getElementById(PDA_BAR_BUTTON_ID))}`,
            `Active endpoint: ${state.activeBaseUrl || '-'}`,
            `Last error: ${state.lastError || '-'}`,
            `Uptime(s): ${Math.floor((Date.now() - state.bootedAt) / 1000)}`
        ];
        return lines.join('\n');
    };

    const ensureDebugBadge = () => {
        if (!isMobileClient() || !document.body) return;
        let badge = document.getElementById(DEBUG_BADGE_ID);
        if (!badge) {
            badge = document.createElement('button');
            badge.id = DEBUG_BADGE_ID;
            badge.type = 'button';
            badge.textContent = 'TI';
            badge.title = 'TornIntel diagnostics';
            badge.style.cssText = [
                'position:fixed',
                'top:calc(8px + env(safe-area-inset-top, 0px))',
                'right:8px',
                'z-index:2147483646',
                'width:36px',
                'height:24px',
                'border:none',
                'border-radius:999px',
                'font-size:11px',
                'font-weight:800',
                'color:#fff',
                'background:#2f7f46',
                'box-shadow:0 6px 14px rgba(0,0,0,0.35)'
            ].join(';');
            badge.addEventListener('click', () => {
                showNotice(collectDiagnostics(), state.lastError ? 'error' : 'info', 30000);
            });
            document.body.appendChild(badge);
        }

        badge.style.background = state.lastError ? '#a32424' : '#2f7f46';
        badge.textContent = state.lastError ? 'ERR' : 'TI';
    };

    const reportScriptError = (context, err) => {
        const reason = `[${context}] ${formatError(err)}`;
        state.lastError = reason;
        console.error('[TornIntel] script error', context, err);
        ensureDebugBadge();
        showNotice(`TornIntel mobile error\n${reason}`, 'error', 30000);
    };

    const configureEndpoint = () => {
        const current = getOverrideBaseUrl() || state.activeBaseUrl || '';
        const input = window.prompt(
            'Optional override URL (example: http://192.168.1.50:8765). Leave blank to use automatic discovery.',
            current
        );

        if (input === null) return;

        const candidate = trimSlash(input);
        if (!candidate) {
            setOverrideBaseUrl('');
            state.activeBaseUrl = null;
            showNotice('Cleared override URL. Automatic endpoint discovery is now enabled.', 'info');
            return;
        }

        if (!isHttpUrl(candidate)) {
            showNotice('Invalid URL. Example: http://192.168.1.50:8765', 'error');
            return;
        }

        setOverrideBaseUrl(candidate);
        state.activeBaseUrl = null;
        showNotice(`Saved override revive listener URL: ${candidate}`, 'success');
    };

    gmRegisterMenuCommandSafe('TornIntel: Set/Clear Revive Listener Override URL', configureEndpoint);

    const $ = (s, p = document) => p.querySelector(s);

    const gmRequest = (method, url, data = null, timeoutMs = 2500) => new Promise((resolve, reject) => {
        if (typeof GM_xmlhttpRequest === 'function') {
            GM_xmlhttpRequest({
                method,
                url,
                headers: { 'Content-Type': 'application/json' },
                data: data ? JSON.stringify(data) : undefined,
                timeout: timeoutMs,
                onload: r => {
                    if (r.status >= 200 && r.status < 300) {
                        try {
                            resolve(JSON.parse(r.responseText));
                        } catch {
                            resolve({ ok: true, raw: r.responseText });
                        }
                    } else {
                        reject(new Error(`HTTP ${r.status}`));
                    }
                },
                ontimeout: () => reject(new Error('Local listener timed out')),
                onerror: () => reject(new Error('Local listener offline'))
            });
            return;
        }

        const controller = new AbortController();
        const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
        fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: data ? JSON.stringify(data) : undefined,
            signal: controller.signal,
            credentials: 'omit',
            mode: 'cors'
        }).then(async (res) => {
            const text = await res.text();
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }
            try {
                resolve(JSON.parse(text));
            } catch {
                resolve({ ok: true, raw: text });
            }
        }).catch((err) => {
            if (String(err?.name || '').toLowerCase() === 'aborterror') {
                reject(new Error('Local listener timed out'));
                return;
            }
            reject(new Error('Local listener offline'));
        }).finally(() => {
            window.clearTimeout(timeoutId);
        });
    });

    const readCachedDiscoveredUrls = () => {
        const cachedRaw = gmGetValue(DISCOVERED_BASE_URLS_KEY, '');
        if (cachedRaw) {
            try {
                const parsed = JSON.parse(String(cachedRaw));
                const urls = normalizeUrls(parsed);
                if (urls.length > 0) return urls;
            } catch {
                // Fall through to legacy key.
            }
        }

        // Backward compatibility with old single-url cache.
        const legacy = trimSlash(gmGetValue(DISCOVERED_BASE_URL_KEY, ''));
        return normalizeUrls([legacy]);
    };

    const fetchDiscoveredBaseUrls = async (forceRefresh = false) => {
        const now = Date.now();
        const cachedAt = Number(gmGetValue(DISCOVERED_BASE_URL_AT_KEY, 0));
        const cachedUrls = readCachedDiscoveredUrls();

        if (!forceRefresh && cachedUrls.length > 0 && cachedAt > 0 && (now - cachedAt) < DISCOVERY_CACHE_MS) {
            return cachedUrls;
        }

        if (state.discoveryPromise) {
            return state.discoveryPromise;
        }

        state.discoveryPromise = (async () => {
            try {
                const res = await gmRequest('GET', DISCOVERY_URL);
                const discoveredUrls = normalizeUrls([
                    ...(Array.isArray(res?.base_urls) ? res.base_urls : []),
                    res?.base_url || ''
                ]);
                if (discoveredUrls.length === 0) {
                    return [];
                }
                gmSetValue(DISCOVERED_BASE_URLS_KEY, JSON.stringify(discoveredUrls));
                gmSetValue(DISCOVERED_BASE_URL_KEY, discoveredUrls[0]);
                gmSetValue(DISCOVERED_BASE_URL_AT_KEY, now);
                return discoveredUrls;
            } catch {
                return cachedUrls;
            } finally {
                state.discoveryPromise = null;
            }
        })();

        return state.discoveryPromise;
    };

    const resolveBaseUrl = async () => {
        // Keep a validated remote/LAN endpoint sticky, but do not keep localhost sticky.
        if (state.activeBaseUrl && !isLocalFallbackUrl(state.activeBaseUrl)) return state.activeBaseUrl;

        const override = getOverrideBaseUrl();
        const discovered = await fetchDiscoveredBaseUrls(false);
        const candidates = unique([override, ...discovered, ...DEFAULT_BASE_URLS].map(trimSlash));
        state.lastCandidates = candidates;
        console.info('[TornIntel] Resolving revive listener endpoint', { override, discovered, candidates });

        for (const baseUrl of candidates) {
            if (!isHttpUrl(baseUrl)) continue;
            try {
                const res = await gmRequest('GET', endpoint(baseUrl, '/health'));
                if (res && res.ok) {
                    state.activeBaseUrl = baseUrl;
                    console.info('[TornIntel] Selected revive listener endpoint', { baseUrl, source: 'candidate' });
                    return baseUrl;
                }
            } catch (_err) {
                // Try the next candidate.
            }
        }

        // Cached discovery may be stale after endpoint changes; force one network refresh.
        const refreshedDiscovered = await fetchDiscoveredBaseUrls(true);
        const refreshedCandidates = unique([override, ...refreshedDiscovered, ...DEFAULT_BASE_URLS].map(trimSlash));
        state.lastCandidates = refreshedCandidates;
        console.info('[TornIntel] Retrying endpoint resolution after forced discovery refresh', {
            override,
            refreshedDiscovered,
            refreshedCandidates
        });
        for (const baseUrl of refreshedCandidates) {
            if (!isHttpUrl(baseUrl)) continue;
            try {
                const res = await gmRequest('GET', endpoint(baseUrl, '/health'));
                if (res && res.ok) {
                    state.activeBaseUrl = baseUrl;
                    console.info('[TornIntel] Selected revive listener endpoint', { baseUrl, source: 'refreshed-candidate' });
                    return baseUrl;
                }
            } catch (_err) {
                // Try the next candidate.
            }
        }

        throw new Error(`No reachable revive listener URL found. Tried: ${refreshedCandidates.join(', ')}`);
    };

    const checkListener = async () => {
        const baseUrl = await resolveBaseUrl();
        const res = await gmRequest('GET', endpoint(baseUrl, '/health'));
        if (!res || !res.ok) {
            throw new Error(`Revive listener health check failed at ${baseUrl}`);
        }
        return { res, baseUrl };
    };

    const parseIdFromHref = href => href?.match(/XID=(\d+)/)?.[1] || null;

    const getCurrentUser = () => {
        try {
            const key = Object.keys(sessionStorage).find(k => /sidebarData\d+/.test(k));
            if (!key) return { requester_name: null, requester_id: null };
            const data = JSON.parse(sessionStorage.getItem(key));
            return {
                requester_name: data?.user?.name || null,
                requester_id: data?.user?.userID || null,
            };
        } catch {
            return { requester_name: null, requester_id: null };
        }
    };

    const getProfileTarget = () => {
        const userId = window.location.href.match(/XID=(\d+)/)?.[1] || null;
        const name = $('.profile-container .profile-container-description .profile-container-description-status h4 > span.m-hide')?.textContent?.trim() || null;
        return { target_id: userId ? parseInt(userId, 10) : null, target_name: name };
    };

    const buildPayoutTemplate = (requesterName, targetName, reviverName, revivedAt) => {
        return [
            'Payout template:',
            `${requesterName}, your revive request for ${targetName} was fulfilled by ${reviverName} at ${revivedAt}.`,
            'Please send the agreed payout when you can.'
        ].join('\n');
    };

    const showNotificationNotice = item => {
        const eventType = String(item.event_type || 'revive_request_fulfilled').toLowerCase();
        const target = item.target_name || `Target ${item.target_id || '?'}`;
        const requester = item.requester_name || 'requester';

        if (eventType === 'revive_request_received' || eventType === 'request_received') {
            showNotice([
                `New revive request received for ${target}`,
                `Requester: ${requester}`,
                item.notes ? `Notes: ${item.notes}` : null,
                item.source ? `Source: ${item.source}` : null,
                item.requested_timestamp ? `Requested at: ${new Date(item.requested_timestamp * 1000).toLocaleString()}` : null
            ].filter(Boolean).join('\n\n'), 'info');
            return;
        }

        const reviver = item.fulfilled_by_name || item.fulfilled_by_id || 'unknown reviver';
        const revivedAt = item.revived_timestamp
            ? new Date(item.revived_timestamp * 1000).toLocaleString()
            : 'unknown time';
        const payoutTemplate = buildPayoutTemplate(requester, target, reviver, revivedAt);

        showNotice([
            `Revive fulfilled for ${target}`,
            `Reviver: ${reviver}`,
            `Revived at: ${revivedAt}`,
            payoutTemplate
        ].join('\n\n'), 'success');
    };

    const inHospital = () => {
        const mainDesc = $('.profile-container .main-desc');
        if (mainDesc && mainDesc.textContent.toLowerCase().includes('in hospital')) return true;
        return Boolean($('li[class*="user-status"][class*="Hospital"]'));
    };

    const findButtonContainer = () => {
        const isVisibleElement = (node) => {
            if (!node) return false;
            const style = window.getComputedStyle(node);
            if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || '1') === 0) {
                return false;
            }
            const rect = node.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        };

        const selectors = [
            '.buttons-wrap .buttons-list',
            '.header-buttons-wrapper',
            '.profile-container .buttons-wrap',
            '.profile-container .profile-buttons',
            '.profile-container .profile-container-content'
        ];

        for (const selector of selectors) {
            const node = $(selector);
            if (isVisibleElement(node)) return node;
        }

        return null;
    };

    const applyButtonStyle = (btn, mode) => {
        if (mode === 'floating') {
            btn.style.cssText = [
                'position:fixed',
                'right:12px',
                'bottom:calc(16px + env(safe-area-inset-bottom, 0px))',
                'z-index:2147483646',
                'padding:10px 12px',
                'background:#b71c1c',
                'color:#fff',
                'border:none',
                'border-radius:8px',
                'cursor:pointer',
                'font-weight:700',
                'font-size:13px',
                'box-shadow:0 10px 24px rgba(0,0,0,0.35)'
            ].join(';');
            return;
        }

        btn.style.cssText = 'margin:8px 0;padding:6px 12px;background:#b71c1c;color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:bold;';
    };

    const isMobileClient = () => {
        try {
            const ua = String(navigator.userAgent || '');
            const touch = (navigator.maxTouchPoints || 0) > 0;
            const narrowViewport = Math.max(window.innerWidth || 0, window.innerHeight || 0) <= 1024;
            return touch || narrowViewport || /Android|iPhone|iPad|iPod|Mobile|Torn\s*PDA/i.test(ua);
        } catch {
            return false;
        }
    };

    const ensurePdaBarButtonStyle = () => {
        if (document.getElementById('tornintel-revive-pda-bar-btn-style')) return;
        gmAddStyleSafe(`
            #tornintel-revive-pda-bar-btn-style {}
            .tornintel-revive-pda-bar-btn {
                border: none;
                border-radius: 10px;
                background: linear-gradient(180deg, #d12424 0%, #8f1414 100%);
                color: #ffffff;
                font-size: 11px;
                font-weight: 800;
                line-height: 1;
                padding: 8px 10px;
                margin-left: 6px;
                min-height: 30px;
                box-shadow: 0 6px 14px rgba(0, 0, 0, 0.35);
                white-space: nowrap;
            }
        `);
        const styleTag = document.createElement('style');
        styleTag.id = 'tornintel-revive-pda-bar-btn-style';
        styleTag.textContent = '';
        (document.head || document.documentElement || document.body).appendChild(styleTag);
    };

    const findPdaStatsAnchor = () => {
        const selectorCandidates = [
            '[title*="stats" i]',
            '[aria-label*="stats" i]',
            '[data-tab*="stats" i]',
            'a[href*="stats" i]'
        ];

        for (const selector of selectorCandidates) {
            const node = document.querySelector(selector);
            if (node) return node;
        }

        const iconLike = Array.from(document.querySelectorAll('a,button,div,span')).find((node) => {
            const title = String(node.getAttribute('title') || '').toLowerCase();
            const aria = String(node.getAttribute('aria-label') || '').toLowerCase();
            const text = String(node.textContent || '').toLowerCase().trim();
            return title.includes('stats') || aria.includes('stats') || text === 'stats';
        });

        return iconLike || null;
    };

    const tryMountPdaBarButton = () => {
        if (!isMobileClient()) return false;
        if (!document.body) return false;
        if (document.getElementById(PDA_BAR_BUTTON_ID)) return true;

        const statsAnchor = findPdaStatsAnchor();
        if (!statsAnchor) {
            debugLog('PDA bar mount skipped: stats anchor not found');
            return false;
        }

        const parent = statsAnchor.parentElement;
        if (!parent) return false;

        ensurePdaBarButtonStyle();
        const btn = document.createElement('button');
        btn.id = PDA_BAR_BUTTON_ID;
        btn.type = 'button';
        btn.className = 'tornintel-revive-pda-bar-btn';
        btn.textContent = 'Revive';
        btn.title = 'Local Revive Request';
        btn.setAttribute('aria-label', 'Local Revive Request');
        btn.addEventListener('click', async (event) => {
            event?.preventDefault?.();
            event?.stopPropagation?.();
            await submitReviveRequest(btn);
        });

        if (statsAnchor.nextSibling) {
            parent.insertBefore(btn, statsAnchor.nextSibling);
        } else {
            parent.appendChild(btn);
        }

        state.lastError = null;
        ensureDebugBadge();
        console.info('[TornIntel] PDA bar Revive button mounted near stats anchor.');
        debugLog('PDA bar Revive button mounted near stats anchor');
        return true;
    };

    const readIconPosition = () => {
        try {
            const raw = String(gmGetValue(ICON_POS_KEY, ''));
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            const x = Number(parsed?.x);
            const y = Number(parsed?.y);
            if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
            return { x, y };
        } catch {
            return null;
        }
    };

    const saveIconPosition = (x, y) => {
        gmSetValue(ICON_POS_KEY, JSON.stringify({ x: Math.round(x), y: Math.round(y) }));
    };

    const clampIconPosition = (x, y, width, height) => {
        const maxX = Math.max(8, window.innerWidth - width - 8);
        const maxY = Math.max(8, window.innerHeight - height - 8);
        const safeX = Math.min(Math.max(8, x), maxX);
        const safeY = Math.min(Math.max(8, y), maxY);
        return { x: safeX, y: safeY };
    };

    const ensureIconStyles = () => {
        if (document.getElementById('tornintel-revive-icon-style')) return;
        gmAddStyleSafe(`
            #tornintel-revive-icon-style {}
            .tornintel-revive-icon {
                position: fixed;
                z-index: 2147483646;
                min-width: 76px;
                height: 44px;
                border: none;
                border-radius: 999px;
                background: linear-gradient(180deg, #d12424 0%, #8f1414 100%);
                color: #ffffff;
                box-shadow: 0 10px 24px rgba(0, 0, 0, 0.45);
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 0 14px;
                font-size: 13px;
                font-weight: 800;
                letter-spacing: 0.2px;
                line-height: 1.1;
                user-select: none;
                -webkit-user-select: none;
                touch-action: none;
            }
            .tornintel-revive-icon:active {
                transform: scale(0.98);
            }
        `);
        const styleTag = document.createElement('style');
        styleTag.id = 'tornintel-revive-icon-style';
        styleTag.textContent = '';
        document.head.appendChild(styleTag);
    };

    const submitReviveRequest = async (trigger) => {
        if (trigger?.dataset?.busy === '1') return;
        if (trigger) {
            trigger.dataset.busy = '1';
            trigger.disabled = true;
        }

        const previousText = trigger?.textContent;
        if (trigger && trigger.id === BUTTON_ID) {
            trigger.textContent = 'Submitting...';
        }

        try {
            const { requester_name, requester_id } = getCurrentUser();
            const { target_id, target_name } = getProfileTarget();

            if (!requester_id || !requester_name) {
                showNotice('Could not determine your Torn user identity.', 'error');
                return;
            }

            if (!target_id && !target_name) {
                showNotice('Could not determine target identity.', 'error');
                return;
            }

            if (!inHospital()) {
                showNotice('Target is not currently shown as hospitalized.', 'error');
                return;
            }

            try {
                const health = await checkListener();
                console.info('[TornIntel] Health check passed', { baseUrl: health.baseUrl });
            } catch (err) {
                showNotice([
                    'Revive listener is offline or unreachable.',
                    'Start it with: python main.py revive_listener serve --host 0.0.0.0 --port 8765',
                    `Tried endpoints: ${state.lastCandidates.join(', ') || 'none'}`,
                    err.message
                ].join('\n\n'), 'error');
                return;
            }

            const payload = {
                requested_at: Math.floor(Date.now() / 1000),
                requester_name,
                requester_id,
                target_id,
                target_name,
                source: 'tampermonkey-local',
                notes: `Requested from ${window.location.href}`,
            };

            try {
                const baseUrl = await resolveBaseUrl();
                const res = await gmRequest('POST', endpoint(baseUrl, '/revive-request'), payload);
                if (!res.ok) throw new Error(res.error || 'unknown_error');
                const request = res.request || {};
                const status = request.status || 'pending';
                showNotice([
                    `Revive request sent as ${status}.`,
                    `Endpoint: ${baseUrl}`,
                    'Listener will post lifecycle updates automatically.'
                ].filter(Boolean).join('\n\n'), status === 'fulfilled' ? 'success' : 'info');
            } catch (err) {
                showNotice([
                    'Failed to save local revive request.',
                    `Active endpoint: ${state.activeBaseUrl || 'none'}`,
                    `Tried endpoints: ${state.lastCandidates.join(', ') || 'none'}`,
                    err.message
                ].join('\n\n'), 'error');
            }
        } catch (err) {
            const message = err?.message || String(err);
            console.error('[TornIntel] revive request action error', err);
            state.lastError = `[submit] ${message}`;
            ensureDebugBadge();
            showNotice(`Unexpected error in revive request script: ${message}`, 'error');
        } finally {
            if (trigger) {
                trigger.dataset.busy = '0';
                trigger.disabled = false;
                if (trigger.id === BUTTON_ID && previousText) {
                    trigger.textContent = previousText;
                }
            }
        }
    };

    const addDraggableMobileIcon = (force = false) => {
        if (!force && !isMobileClient()) return;
        if (document.getElementById(ICON_ID)) return;
        if (!document.body) return;

        debugLog(`Trying draggable mobile icon mount (force=${force})`);

        ensureIconStyles();
        const icon = document.createElement('button');
        icon.id = ICON_ID;
        icon.type = 'button';
        icon.className = 'tornintel-revive-icon';
        icon.textContent = 'Revive';
        icon.title = 'Local Revive Request';
        icon.setAttribute('aria-label', 'Local Revive Request');

        try {
            document.body.appendChild(icon);
        } catch (err) {
            reportScriptError('icon_append', err);
            return;
        }

        const rect = icon.getBoundingClientRect();
        const saved = readIconPosition();
        const fallback = {
            x: Math.max(8, window.innerWidth - rect.width - 12),
            y: Math.max(8, (window.innerHeight * 0.5) - (rect.height * 0.5))
        };
        const position = clampIconPosition(
            saved?.x ?? fallback.x,
            saved?.y ?? fallback.y,
            rect.width,
            rect.height
        );
        icon.style.left = `${position.x}px`;
        icon.style.top = `${position.y}px`;

        let startX = 0;
        let startY = 0;
        let originX = position.x;
        let originY = position.y;
        let dragMoved = false;
        let pointerId = null;

        const onPointerMove = (event) => {
            if (pointerId === null || event.pointerId !== pointerId) return;
            const dx = event.clientX - startX;
            const dy = event.clientY - startY;
            if (!dragMoved && Math.hypot(dx, dy) > ICON_DRAG_THRESHOLD) {
                dragMoved = true;
                state.iconDragging = true;
            }
            const next = clampIconPosition(originX + dx, originY + dy, icon.offsetWidth || 76, icon.offsetHeight || 44);
            icon.style.left = `${next.x}px`;
            icon.style.top = `${next.y}px`;
        };

        const onPointerUp = async (event) => {
            if (pointerId === null || event.pointerId !== pointerId) return;
            pointerId = null;
            icon.releasePointerCapture(event.pointerId);
            window.removeEventListener('pointermove', onPointerMove);
            window.removeEventListener('pointerup', onPointerUp);
            window.removeEventListener('pointercancel', onPointerUp);

            const left = Number.parseFloat(icon.style.left || '0') || 0;
            const top = Number.parseFloat(icon.style.top || '0') || 0;
            saveIconPosition(left, top);

            const shouldSubmit = !dragMoved;
            window.setTimeout(() => {
                state.iconDragging = false;
            }, 20);

            if (shouldSubmit) {
                await submitReviveRequest(icon);
            }
        };

        if (window.PointerEvent) {
            icon.addEventListener('pointerdown', (event) => {
                pointerId = event.pointerId;
                dragMoved = false;
                startX = event.clientX;
                startY = event.clientY;
                originX = Number.parseFloat(icon.style.left || '0') || 0;
                originY = Number.parseFloat(icon.style.top || '0') || 0;
                icon.setPointerCapture(event.pointerId);
                window.addEventListener('pointermove', onPointerMove, { passive: true });
                window.addEventListener('pointerup', onPointerUp);
                window.addEventListener('pointercancel', onPointerUp);
            });
        } else {
            icon.addEventListener('click', async (event) => {
                event?.preventDefault?.();
                event?.stopPropagation?.();
                await submitReviveRequest(icon);
            });
        }

        window.addEventListener('resize', () => {
            const next = clampIconPosition(
                Number.parseFloat(icon.style.left || '0') || 0,
                Number.parseFloat(icon.style.top || '0') || 0,
                icon.offsetWidth || 76,
                icon.offsetHeight || 44
            );
            icon.style.left = `${next.x}px`;
            icon.style.top = `${next.y}px`;
            saveIconPosition(next.x, next.y);
        });

        state.lastError = null;
        ensureDebugBadge();
        console.info('[TornIntel] Draggable mobile revive icon mounted.');
        debugLog('Draggable mobile icon mounted');
    };

    const addButton = () => {
        if ($(`#${BUTTON_ID}`)) return;
        if (!document.body) return;

        if (isMobileClient()) {
            const mountedInBar = tryMountPdaBarButton();
            if (mountedInBar) return;
            addDraggableMobileIcon();
            return;
        }

        const container = findButtonContainer();
        const mode = container ? 'inline' : 'floating';

        const btn = document.createElement('button');
        btn.id = BUTTON_ID;
        btn.type = 'button';
        btn.textContent = 'Local Revive Request';
        applyButtonStyle(btn, mode);

        btn.onclick = async (event) => {
            event?.preventDefault?.();
            event?.stopPropagation?.();
            await submitReviveRequest(btn);
        };

        if (container) {
            container.appendChild(btn);
        } else {
            document.body.appendChild(btn);
            console.info('[TornIntel] Using floating revive button fallback (mobile/PDA container not found).');
        }
    };

    const startButtonMounting = () => {
        const emitDelayedDiagnosticsIfMissing = () => {
            window.setTimeout(() => {
                if (state.debugPopupShown) return;
                if (hasVisibleControl()) return;

                state.debugPopupShown = true;
                const statsAnchorFound = Boolean(findPdaStatsAnchor());
                const details = [
                    'No revive control mounted after startup delay.',
                    `mobile=${isMobileClient()}`,
                    `body=${Boolean(document.body)}`,
                    `statsAnchor=${statsAnchorFound}`,
                    `pointerEvent=${Boolean(window.PointerEvent)}`,
                    `gmRequest=${typeof GM_xmlhttpRequest === 'function'}`,
                    `gmMenu=${typeof GM_registerMenuCommand === 'function'}`,
                    `lastError=${state.lastError || '-'}`,
                    `mountPasses=${state.mountPasses}`
                ].join(' | ');

                debugLog(details, true);
            }, DEBUG_DIAGNOSTIC_DELAY_MS);
        };

        const boot = () => {
            if (!document.body) {
                window.setTimeout(boot, 250);
                return;
            }

            try {
                state.mountPasses += 1;
                debugLog(`Mount pass ${state.mountPasses} started`);
                ensureDebugBadge();
                addButton();

                if (isMobileClient()) {
                    tryMountPdaBarButton();
                    addDraggableMobileIcon();
                }

                // If no visible control exists after normal mounting, force the draggable fallback.
                if (!document.getElementById(BUTTON_ID) && !document.getElementById(PDA_BAR_BUTTON_ID) && !document.getElementById(ICON_ID)) {
                    addDraggableMobileIcon(true);
                }

                debugLog(
                    `Mount pass ${state.mountPasses} result: button=${Boolean(document.getElementById(BUTTON_ID))}, pdaBar=${Boolean(document.getElementById(PDA_BAR_BUTTON_ID))}, icon=${Boolean(document.getElementById(ICON_ID))}`
                );
            } catch (err) {
                reportScriptError('boot', err);
            }

            if (!state.buttonObserverStarted) {
                new MutationObserver(() => {
                    try {
                        ensureDebugBadge();
                        addButton();
                        if (isMobileClient()) {
                            tryMountPdaBarButton();
                            addDraggableMobileIcon();
                        }
                        if (!document.getElementById(BUTTON_ID) && !document.getElementById(PDA_BAR_BUTTON_ID) && !document.getElementById(ICON_ID)) {
                            addDraggableMobileIcon(true);
                        }
                    } catch (err) {
                        reportScriptError('observer', err);
                    }
                }).observe(document.body, { childList: true, subtree: true });
                state.buttonObserverStarted = true;
            }

            if (!state.buttonRecheckTimer) {
                state.buttonRecheckTimer = window.setInterval(() => {
                    try {
                        ensureDebugBadge();
                        addButton();
                        if (isMobileClient()) {
                            tryMountPdaBarButton();
                            addDraggableMobileIcon();
                        }
                        if (!document.getElementById(BUTTON_ID) && !document.getElementById(PDA_BAR_BUTTON_ID) && !document.getElementById(ICON_ID)) {
                            addDraggableMobileIcon(true);
                        }
                    } catch (err) {
                        reportScriptError('interval', err);
                    }
                }, BUTTON_RECHECK_MS);
            }
        };

        emitDelayedDiagnosticsIfMissing();
        boot();
    };

    window.addEventListener('error', (event) => {
        reportScriptError('window_error', event?.error || new Error(String(event?.message || 'window_error')));
    });

    window.addEventListener('unhandledrejection', (event) => {
        reportScriptError('unhandled_rejection', event?.reason || new Error('unhandled_rejection'));
    });

    const startNotificationPolling = () => {
        if (state.notificationTimer) return;

        let pollInFlight = false;

        const schedulePoll = (delayMs = 0) => {
            if (state.notificationTimer) {
                window.clearTimeout(state.notificationTimer);
            }
            state.notificationTimer = window.setTimeout(poll, delayMs);
        };

        const poll = async () => {
            if (pollInFlight) return;
            pollInFlight = true;
            const { requester_name, requester_id } = getCurrentUser();
            if (!requester_id && !requester_name) {
                pollInFlight = false;
                schedulePoll(5000);
                return;
            }

            try {
                const baseUrl = await resolveBaseUrl();
                const query = requester_id
                    ? `?requester_id=${encodeURIComponent(requester_id)}&limit=10&wait=25`
                    : `?requester_name=${encodeURIComponent(requester_name)}&limit=10&wait=25`;
                const res = await gmRequest('GET', `${endpoint(baseUrl, '/revive-request/notifications')}${query}`, null, 30000);
                if (!res || !res.ok || !Array.isArray(res.notifications)) return;

                for (const item of res.notifications) {
                    showNotificationNotice(item);
                }
            } catch (_err) {
                // Listener offline should not spam alerts during passive polling.
            } finally {
                pollInFlight = false;
                schedulePoll(0);
            }
        };

        schedulePoll(0);
    };

    startButtonMounting();
    startNotificationPolling();
})();