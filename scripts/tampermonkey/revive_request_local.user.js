// ==UserScript==
// @name         TornIntel Local Revive Request
// @namespace    http://tampermonkey.net/
// @version      0.4.9
// @description  Send local revive requests into TornIntel over a local HTTP listener.
// @author       TornIntel
// @match        https://www.torn.com/*
// @connect      *
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @homepageURL  https://github.com/xDp64xG/Torn-Intel
// @supportURL   https://github.com/xDp64xG/Torn-Intel/issues
// Ping Check
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

    const trimSlash = url => String(url || '').replace(/\/+$/, '');
    const isHttpUrl = url => /^https?:\/\/.+/i.test(String(url || ''));
    const unique = values => [...new Set(values.filter(Boolean))];
    const normalizeUrls = values => unique((Array.isArray(values) ? values : [values]).map(trimSlash).filter(isHttpUrl));
    const isLocalFallbackUrl = url => /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/i.test(trimSlash(url));

    const state = {
        activeBaseUrl: null,
        discoveryPromise: null,
        notificationTimer: null,
        lastCandidates: []
    };

    const getOverrideBaseUrl = () => trimSlash(GM_getValue(BASE_URL_KEY, ''));
    const setOverrideBaseUrl = url => GM_setValue(BASE_URL_KEY, trimSlash(url));

    const endpoint = (baseUrl, path) => `${trimSlash(baseUrl)}${path}`;

    const ensureNoticeStyles = () => {
        if (document.getElementById('tornintel-revive-notice-style')) return;
        GM_addStyle(`
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

    GM_registerMenuCommand('TornIntel: Set/Clear Revive Listener Override URL', configureEndpoint);

    const $ = (s, p = document) => p.querySelector(s);

    const gmRequest = (method, url, data = null, timeoutMs = 2500) => new Promise((resolve, reject) => {
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
    });

    const readCachedDiscoveredUrls = () => {
        const cachedRaw = GM_getValue(DISCOVERED_BASE_URLS_KEY, '');
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
        const legacy = trimSlash(GM_getValue(DISCOVERED_BASE_URL_KEY, ''));
        return normalizeUrls([legacy]);
    };

    const fetchDiscoveredBaseUrls = async (forceRefresh = false) => {
        const now = Date.now();
        const cachedAt = Number(GM_getValue(DISCOVERED_BASE_URL_AT_KEY, 0));
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
                GM_setValue(DISCOVERED_BASE_URLS_KEY, JSON.stringify(discoveredUrls));
                GM_setValue(DISCOVERED_BASE_URL_KEY, discoveredUrls[0]);
                GM_setValue(DISCOVERED_BASE_URL_AT_KEY, now);
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
        const selectors = [
            '.buttons-wrap .buttons-list',
            '.header-buttons-wrapper',
            '.profile-container .buttons-wrap',
            '.profile-container .profile-buttons',
            '.profile-container .profile-container-content'
        ];

        for (const selector of selectors) {
            const node = $(selector);
            if (node) return node;
        }

        return null;
    };

    const applyButtonStyle = (btn, mode) => {
        if (mode === 'floating') {
            btn.style.cssText = [
                'position:fixed',
                'left:12px',
                'bottom:16px',
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

    const addButton = () => {
        if ($(`#${BUTTON_ID}`)) return;
        if (!document.body) return;

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

            if (btn.dataset.busy === '1') return;
            btn.dataset.busy = '1';
            const previousText = btn.textContent;
            btn.textContent = 'Submitting...';
            btn.disabled = true;

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
                console.error('[TornIntel] revive request button error', err);
                showNotice(`Unexpected error in revive request script: ${message}`, 'error');
            } finally {
                btn.dataset.busy = '0';
                btn.textContent = previousText;
                btn.disabled = false;
            }
        };

        if (container) {
            container.appendChild(btn);
        } else {
            document.body.appendChild(btn);
            console.info('[TornIntel] Using floating revive button fallback (mobile/PDA container not found).');
        }
    };

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

    addButton();
    new MutationObserver(() => addButton()).observe(document.body, { childList: true, subtree: true });
    startNotificationPolling();
})();