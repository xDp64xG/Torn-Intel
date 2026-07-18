// ==UserScript==
// @name         TornIntel Local Revive Request
// @namespace    http://tampermonkey.net/
// @version      0.4.4
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
    const DISCOVERED_BASE_URL_AT_KEY = 'tornintel_revive_listener_base_url_discovered_at';
    const DISCOVERY_CACHE_MS = 5 * 60 * 1000;
    const NOTIFICATION_POLL_MS = 15000;

    const trimSlash = url => String(url || '').replace(/\/+$/, '');
    const isHttpUrl = url => /^https?:\/\/.+/i.test(String(url || ''));
    const unique = values => [...new Set(values.filter(Boolean))];

    const state = {
        activeBaseUrl: null,
        discoveryPromise: null,
        notificationTimer: null,
        lastCandidates: []
    };

    const getOverrideBaseUrl = () => trimSlash(GM_getValue(BASE_URL_KEY, ''));
    const setOverrideBaseUrl = url => GM_setValue(BASE_URL_KEY, trimSlash(url));

    const endpoint = (baseUrl, path) => `${trimSlash(baseUrl)}${path}`;

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
            alert('Cleared override URL. Automatic endpoint discovery is now enabled.');
            return;
        }

        if (!isHttpUrl(candidate)) {
            alert('Invalid URL. Example: http://192.168.1.50:8765');
            return;
        }

        setOverrideBaseUrl(candidate);
        state.activeBaseUrl = null;
        alert(`Saved override revive listener URL: ${candidate}`);
    };

    GM_registerMenuCommand('TornIntel: Set/Clear Revive Listener Override URL', configureEndpoint);

    const $ = (s, p = document) => p.querySelector(s);

    const gmRequest = (method, url, data = null) => new Promise((resolve, reject) => {
        GM_xmlhttpRequest({
            method,
            url,
            headers: { 'Content-Type': 'application/json' },
            data: data ? JSON.stringify(data) : undefined,
            timeout: 2500,
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

    const fetchDiscoveredBaseUrl = async (forceRefresh = false) => {
        const now = Date.now();
        const cachedAt = Number(GM_getValue(DISCOVERED_BASE_URL_AT_KEY, 0));
        const cachedUrl = trimSlash(GM_getValue(DISCOVERED_BASE_URL_KEY, ''));

        if (!forceRefresh && cachedUrl && cachedAt > 0 && (now - cachedAt) < DISCOVERY_CACHE_MS) {
            return cachedUrl;
        }

        if (state.discoveryPromise) {
            return state.discoveryPromise;
        }

        state.discoveryPromise = (async () => {
            try {
                const res = await gmRequest('GET', DISCOVERY_URL);
                const candidate = trimSlash(res?.base_url || '');
                if (!isHttpUrl(candidate)) {
                    return '';
                }
                GM_setValue(DISCOVERED_BASE_URL_KEY, candidate);
                GM_setValue(DISCOVERED_BASE_URL_AT_KEY, now);
                return candidate;
            } catch {
                return cachedUrl || '';
            } finally {
                state.discoveryPromise = null;
            }
        })();

        return state.discoveryPromise;
    };

    const resolveBaseUrl = async () => {
        if (state.activeBaseUrl) return state.activeBaseUrl;

        const override = getOverrideBaseUrl();
        const discovered = await fetchDiscoveredBaseUrl(false);
        const candidates = unique([override, discovered, ...DEFAULT_BASE_URLS].map(trimSlash));
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
        const refreshedDiscovered = await fetchDiscoveredBaseUrl(true);
        const refreshedCandidates = unique([override, refreshedDiscovered, ...DEFAULT_BASE_URLS].map(trimSlash));
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

    const showNotificationAlert = item => {
        const eventType = String(item.event_type || 'revive_request_fulfilled').toLowerCase();
        const target = item.target_name || `Target ${item.target_id || '?'}`;
        const requester = item.requester_name || 'requester';

        if (eventType === 'revive_request_received' || eventType === 'request_received') {
            alert([
                `New revive request received for ${target}`,
                `Requester: ${requester}`,
                item.notes ? `Notes: ${item.notes}` : null,
                item.source ? `Source: ${item.source}` : null,
                item.requested_timestamp ? `Requested at: ${new Date(item.requested_timestamp * 1000).toLocaleString()}` : null
            ].filter(Boolean).join('\n\n'));
            return;
        }

        const reviver = item.fulfilled_by_name || item.fulfilled_by_id || 'unknown reviver';
        const revivedAt = item.revived_timestamp
            ? new Date(item.revived_timestamp * 1000).toLocaleString()
            : 'unknown time';
        const payoutTemplate = buildPayoutTemplate(requester, target, reviver, revivedAt);

        alert([
            `Revive fulfilled for ${target}`,
            `Reviver: ${reviver}`,
            `Revived at: ${revivedAt}`,
            payoutTemplate
        ].join('\n\n'));
    };

    const inHospital = () => {
        const mainDesc = $('.profile-container .main-desc');
        if (mainDesc && mainDesc.textContent.toLowerCase().includes('in hospital')) return true;
        return Boolean($('li[class*="user-status"][class*="Hospital"]'));
    };

    const addButton = () => {
        if ($('#tornintel-local-revive-btn')) return;
        const container = $('.buttons-wrap .buttons-list') || $('.header-buttons-wrapper');
        if (!container) return;

        const btn = document.createElement('button');
        btn.id = 'tornintel-local-revive-btn';
        btn.type = 'button';
        btn.textContent = 'Local Revive Request';
        btn.style.cssText = 'margin:8px 0;padding:6px 12px;background:#b71c1c;color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:bold;';

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
                    alert('Could not determine your Torn user identity.');
                    return;
                }

                if (!target_id && !target_name) {
                    alert('Could not determine target identity.');
                    return;
                }

                if (!inHospital()) {
                    alert('Target is not currently shown as hospitalized.');
                    return;
                }

                try {
                    const health = await checkListener();
                    console.info('[TornIntel] Health check passed', { baseUrl: health.baseUrl });
                } catch (err) {
                    alert([
                        'Revive listener is offline or unreachable.',
                        'Start it with: python main.py revive_listener serve --host 0.0.0.0 --port 8765',
                        `Tried endpoints: ${state.lastCandidates.join(', ') || 'none'}`,
                        err.message
                    ].join('\n\n'));
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
                    const by = request.fulfilled_by_name ? ` by ${request.fulfilled_by_name}` : '';
                    const revivedAt = request.revived_timestamp
                        ? new Date(request.revived_timestamp * 1000).toLocaleString()
                        : 'unknown time';
                    const payoutTemplate = buildPayoutTemplate(
                        requester_name,
                        target_name || `target ${target_id || '?'}`,
                        request.fulfilled_by_name || 'unknown reviver',
                        revivedAt
                    );
                    alert([
                        `Revive request saved locally as ${status}${by}`,
                        `Endpoint: ${baseUrl}`,
                        request.fulfilled_by_name ? `Reviver: ${request.fulfilled_by_name}` : null,
                        request.revived_timestamp ? `Revived at: ${revivedAt}` : null,
                        payoutTemplate
                    ].filter(Boolean).join('\n\n'));
                } catch (err) {
                    alert([
                        'Failed to save local revive request.',
                        `Active endpoint: ${state.activeBaseUrl || 'none'}`,
                        `Tried endpoints: ${state.lastCandidates.join(', ') || 'none'}`,
                        err.message
                    ].join('\n\n'));
                }
            } catch (err) {
                const message = err?.message || String(err);
                console.error('[TornIntel] revive request button error', err);
                alert(`Unexpected error in revive request script: ${message}`);
            } finally {
                btn.dataset.busy = '0';
                btn.textContent = previousText;
                btn.disabled = false;
            }
        };

        container.appendChild(btn);
    };

    const startNotificationPolling = () => {
        if (state.notificationTimer) return;

        const poll = async () => {
            const { requester_name, requester_id } = getCurrentUser();
            if (!requester_id && !requester_name) return;

            try {
                const baseUrl = await resolveBaseUrl();
                const query = requester_id
                    ? `?requester_id=${encodeURIComponent(requester_id)}&limit=10`
                    : `?requester_name=${encodeURIComponent(requester_name)}&limit=10`;
                const res = await gmRequest('GET', `${endpoint(baseUrl, '/revive-request/notifications')}${query}`);
                if (!res || !res.ok || !Array.isArray(res.notifications)) return;

                for (const item of res.notifications) {
                    showNotificationAlert(item);
                }
            } catch (_err) {
                // Listener offline should not spam alerts during passive polling.
            }
        };

        state.notificationTimer = window.setInterval(poll, NOTIFICATION_POLL_MS);
        poll();
    };

    addButton();
    new MutationObserver(() => addButton()).observe(document.body, { childList: true, subtree: true });
    startNotificationPolling();
})();