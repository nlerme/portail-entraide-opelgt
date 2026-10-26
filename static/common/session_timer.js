'use strict';

(() => {
  let intervalId = null;
  let expired = false;

  function stop() {
    if (intervalId !== null) window.clearInterval(intervalId);
    intervalId = null;
    expired = false;
  }

  function formatSeconds(totalSeconds) {
    const safe = Math.max(0, Math.ceil(Number(totalSeconds) || 0));
    const minutes = Math.floor(safe / 60);
    const seconds = safe % 60;
    return `${minutes}:${String(seconds).padStart(2, '0')}`;
  }

  function statusClassFor(remainingSeconds, totalSeconds) {
    const remaining = Math.max(0, Number(remainingSeconds) || 0);
    const total = Math.max(1, Number(totalSeconds) || 1);
    if (remaining <= 0) return 'session-expired';
    const ratio = Math.min(1, remaining / total);
    if (ratio <= 1 / 3) return 'session-critical';
    if (ratio <= 2 / 3) return 'session-middle';
    return 'session-safe';
  }

  function applyStatusClass(element, statusClass) {
    for (const className of ['session-safe', 'session-middle', 'session-critical', 'session-warning', 'session-expired']) {
      element.classList.toggle(className, className === statusClass || (className === 'session-warning' && statusClass === 'session-critical'));
    }
  }

  function start({expiresAt, serverTime, durationMinutes, element, onExpire}) {
    stop();
    if (!element || !Number.isFinite(Number(expiresAt))) return;
    const referenceServerTime = Number.isFinite(Number(serverTime)) ? Number(serverTime) : Date.now() / 1000;
    const clockOffset = referenceServerTime - Date.now() / 1000;
    const configuredTotal = Number(durationMinutes) * 60;
    const totalSeconds = Number.isFinite(configuredTotal) && configuredTotal > 0
      ? configuredTotal
      : Math.max(1, Number(expiresAt) - referenceServerTime);

    const tick = () => {
      const remaining = Number(expiresAt) - (Date.now() / 1000 + clockOffset);
      element.textContent = `Temps restant avant déconnexion : ${formatSeconds(remaining)}`;
      applyStatusClass(element, statusClassFor(remaining, totalSeconds));
      if (remaining <= 0 && !expired) {
        expired = true;
        window.clearInterval(intervalId);
        intervalId = null;
        if (typeof onExpire === 'function') onExpire();
      }
    };

    tick();
    intervalId = window.setInterval(tick, 1000);
  }

  window.SessionTimer = {start, stop, formatSeconds, statusClassFor};
})();

(() => {
  let active = false;
  let kind = 'member';
  let csrfToken = '';
  let heartbeatId = null;
  let pageHideHandler = null;

  function paths() {
    return kind === 'admin'
      ? {closing: '/api/admin/session/closing', keepalive: '/api/admin/session/keepalive', logout: '/api/admin/logout', login: '/admin'}
      : {closing: '/api/session/closing', keepalive: '/api/session/keepalive', logout: '/api/logout', login: '/'};
  }

  async function keepalive() {
    if (!active || !csrfToken) return;
    const target = paths().keepalive;
    try {
      await fetch(target, {
        method: 'POST',
        credentials: 'include',
        cache: 'no-store',
        headers: {'X-CSRF-Token': csrfToken},
      });
    } catch {}
  }

  function markClosing() {
    if (!active || !csrfToken) return;
    const body = JSON.stringify({csrfToken});
    const target = paths().closing;
    try {
      fetch(target, {
        method: 'POST',
        credentials: 'include',
        keepalive: true,
        headers: {'Content-Type': 'application/json'},
        body,
      }).catch(() => {});
    } catch {
      try { navigator.sendBeacon(target, new Blob([body], {type: 'application/json'})); } catch {}
    }
  }

  function stop() {
    active = false;
    csrfToken = '';
    if (heartbeatId !== null) window.clearInterval(heartbeatId);
    heartbeatId = null;
    if (pageHideHandler) window.removeEventListener('pagehide', pageHideHandler);
    pageHideHandler = null;
  }

  function start({sessionKind = 'member', token = ''} = {}) {
    stop();
    if (!token) return;
    kind = sessionKind === 'admin' ? 'admin' : 'member';
    csrfToken = token;
    active = true;
    pageHideHandler = markClosing;
    window.addEventListener('pagehide', pageHideHandler);
    keepalive();
    heartbeatId = window.setInterval(keepalive, 10000);
  }

  async function expire() {
    const target = paths();
    const token = csrfToken;
    stop();
    window.SessionTimer?.stop();
    try {
      await fetch(target.logout, {
        method: 'POST',
        credentials: 'include',
        keepalive: true,
        headers: token ? {'X-CSRF-Token': token} : {},
      });
    } catch {}
    window.location.replace(target.login);
  }

  window.SessionLifecycle = {start, stop, expire, keepalive};
})();
