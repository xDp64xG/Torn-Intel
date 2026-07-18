// ==UserScript==
// @name         TornIntel Local Revive Request
// @namespace    http://tampermonkey.net/
// @version      0.1.0
// @description  Send local revive requests into TornIntel over a local HTTP listener.
// @author       TornIntel
// @match        https://www.torn.com/*
// @connect      127.0.0.1
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// ==/UserScript==

(() => {
    'use strict';

    const CONFIG = {
        BASE_URL: 'http://127.0.0.1:8765',
        HEALTH_URL: 'http://127.0.0.1:8765/health',
        REQUEST_URL: 'http://127.0.0.1:8765/revive-request',
        NOTIFICATIONS_URL: 'http://127.0.0.1:8765/revive-request/notifications',
        NOTIFICATION_POLL_MS: 15000
    };

    const state = {
        notificationTimer: null
    };

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

    const checkListener = async () => {
        const res = await gmRequest('GET', CONFIG.HEALTH_URL);
        if (!res || !res.ok) {
            throw new Error('Local revive listener health check failed');
        }
        return res;
    };

    const parseIdFromHref = href => href?.match(/XID=(\d+)/)?.[1] || null;

    const getCurrentUser = () => {
        const key = Object.keys(sessionStorage).find(k => /sidebarData\d+/.test(k));
        if (!key) return { requester_name: null, requester_id: null };
        try {
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
        btn.textContent = 'Local Revive Request';
        btn.style.cssText = 'margin:8px 0;padding:6px 12px;background:#b71c1c;color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:bold;';

        btn.onclick = async () => {
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
                await checkListener();
            } catch (err) {
                alert(`Local revive listener is offline. Start it with: python main.py revive_listener serve\n\n${err.message}`);
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
                const res = await gmRequest('POST', CONFIG.REQUEST_URL, payload);
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
                    request.fulfilled_by_name ? `Reviver: ${request.fulfilled_by_name}` : null,
                    request.revived_timestamp ? `Revived at: ${revivedAt}` : null,
                    payoutTemplate
                ].filter(Boolean).join('\n\n'));
            } catch (err) {
                alert(`Failed to save local revive request: ${err.message}`);
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
                const query = requester_id
                    ? `?requester_id=${encodeURIComponent(requester_id)}&limit=10`
                    : `?requester_name=${encodeURIComponent(requester_name)}&limit=10`;
                const res = await gmRequest('GET', `${CONFIG.NOTIFICATIONS_URL}${query}`);
                if (!res || !res.ok || !Array.isArray(res.notifications)) return;

                for (const item of res.notifications) {
                    const target = item.target_name || `Target ${item.target_id || '?'}`;
                    const reviver = item.fulfilled_by_name || item.fulfilled_by_id || 'unknown reviver';
                    const revivedAt = item.revived_timestamp
                        ? new Date(item.revived_timestamp * 1000).toLocaleString()
                        : 'unknown time';
                    const requester = item.requester_name || 'requester';
                    const payoutTemplate = buildPayoutTemplate(requester, target, reviver, revivedAt);
                    alert([
                        `Revive fulfilled for ${target}`,
                        `Reviver: ${reviver}`,
                        `Revived at: ${revivedAt}`,
                        payoutTemplate
                    ].join('\n\n'));
                }
            } catch (_err) {
                // Listener offline should not spam alerts during passive polling.
            }
        };

        state.notificationTimer = window.setInterval(poll, CONFIG.NOTIFICATION_POLL_MS);
        poll();
    };

    addButton();
    new MutationObserver(() => addButton()).observe(document.body, { childList: true, subtree: true });
    startNotificationPolling();
})();