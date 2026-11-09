'use strict';

(() => {
  const THEME_KEY = 'opelgt-theme';
  const FONT_KEY = 'opelgt-font';
  const FONT_ORDER = ['small', 'normal', 'large'];
  let connectivityTimer = null;
  let connectivityUpdate = null;
  let lastConnectivityStatus = null;

  function storedTheme() {
    const value = localStorage.getItem(THEME_KEY);
    return value === 'dark' ? 'dark' : 'light';
  }

  function storedFont() {
    const value = localStorage.getItem(FONT_KEY);
    if (FONT_ORDER.includes(value)) return value;
    const legacyValue = localStorage.getItem('opelgt-font-scale');
    if (legacyValue !== null && legacyValue !== '') {
      const legacyScale = Number(legacyValue);
      if (Number.isFinite(legacyScale)) {
        if (legacyScale < 0.96) return 'small';
        if (legacyScale > 1.06) return 'large';
      }
    }
    return 'normal';
  }

  function themeControls() {
    return [...document.querySelectorAll('[data-ui-theme], #themeButton, #themeToggle')];
  }

  function fontDecreaseControls() {
    return [...document.querySelectorAll('[data-ui-font-decrease], #fontDecrease')];
  }

  function fontIncreaseControls() {
    return [...document.querySelectorAll('[data-ui-font-increase], #fontIncrease')];
  }

  function refreshThemeControls() {
    const dark = document.documentElement.dataset.theme === 'dark';
    for (const button of themeControls()) {
      const targetLabel = dark ? 'Mode clair' : 'Mode sombre';
      const targetIcon = dark ? '☀' : '☾';
      button.setAttribute('aria-pressed', String(dark));
      button.setAttribute('aria-label', `Activer le ${targetLabel.toLowerCase()}`);
      button.title = `Activer le ${targetLabel.toLowerCase()}`;
      const icon = button.querySelector('[data-theme-icon], #themeIcon');
      const label = button.querySelector('[data-theme-label], #themeLabel');
      if (icon) icon.textContent = targetIcon;
      if (label) label.textContent = targetLabel;
      if (!icon && !label) button.textContent = `${targetIcon} ${targetLabel}`;
    }
  }

  function refreshFontControls() {
    const font = FONT_ORDER.includes(document.documentElement.dataset.font)
      ? document.documentElement.dataset.font
      : 'normal';
    const index = FONT_ORDER.indexOf(font);
    for (const button of fontDecreaseControls()) button.disabled = index === 0;
    for (const button of fontIncreaseControls()) button.disabled = index === FONT_ORDER.length - 1;
  }

  function applyTheme(theme, {persist = true} = {}) {
    const safe = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = safe;
    if (persist) localStorage.setItem(THEME_KEY, safe);
    refreshThemeControls();
    window.dispatchEvent(new CustomEvent('portal-theme-changed', {detail: {theme: safe}}));
  }

  function applyFont(font, {persist = true} = {}) {
    const safe = FONT_ORDER.includes(font) ? font : 'normal';
    document.documentElement.dataset.font = safe;
    if (persist) localStorage.setItem(FONT_KEY, safe);
    localStorage.removeItem('opelgt-font-scale');
    refreshFontControls();
    window.dispatchEvent(new CustomEvent('portal-font-changed', {detail: {font: safe}}));
  }

  function changeFont(delta) {
    const current = FONT_ORDER.includes(document.documentElement.dataset.font)
      ? document.documentElement.dataset.font
      : 'normal';
    const nextIndex = Math.max(0, Math.min(FONT_ORDER.length - 1, FONT_ORDER.indexOf(current) + delta));
    applyFont(FONT_ORDER[nextIndex]);
  }

  function bindControls() {
    for (const button of themeControls()) {
      if (button.dataset.portalUiBound === 'true') continue;
      button.dataset.portalUiBound = 'true';
      button.addEventListener('click', () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
    }
    for (const button of fontDecreaseControls()) {
      if (button.dataset.portalUiBound === 'true') continue;
      button.dataset.portalUiBound = 'true';
      button.addEventListener('click', () => changeFont(-1));
    }
    for (const button of fontIncreaseControls()) {
      if (button.dataset.portalUiBound === 'true') continue;
      button.dataset.portalUiBound = 'true';
      button.addEventListener('click', () => changeFont(1));
    }
    refreshThemeControls();
    refreshFontControls();
  }

  function initialize() {
    applyTheme(storedTheme(), {persist: false});
    applyFont(storedFont(), {persist: false});
    bindControls();
  }

  function renderConnectivity(status) {
    const online = Boolean(status && status.online);
    const conclusive = status?.conclusive !== false;
    lastConnectivityStatus = status || null;
    const detail = String(status && status.detail || '');
    for (const badge of document.querySelectorAll('[data-connectivity-status], #connectivityBadge')) {
      badge.classList.remove('checking', 'online', 'offline');
      if (!conclusive && !online) {
        badge.classList.add('checking');
        badge.innerHTML = '<span aria-hidden="true">●</span> Vérification Internet…';
      } else {
        badge.classList.add(online ? 'online' : 'offline');
        badge.innerHTML = `<span aria-hidden="true">●</span> ${online ? 'Internet disponible' : 'Internet indisponible'}`;
      }
      badge.title = detail;
    }
    return online;
  }

  function renderConnectivityChecking() {
    for (const badge of document.querySelectorAll('[data-connectivity-status], #connectivityBadge')) {
      badge.classList.remove('online', 'offline');
      badge.classList.add('checking');
      badge.innerHTML = '<span aria-hidden="true">●</span> Vérification Internet…';
    }
  }

  async function refreshConnectivity(url = '/api/connectivity') {
    renderConnectivityChecking();
    try {
      const response = await fetch(`${url}${url.includes('?') ? '&' : '?'}force=true`, {
        cache: 'no-store',
        credentials: 'include',
      });
      let payload = {};
      try { payload = await response.json(); } catch {}
      if (!response.ok) throw new Error(payload.message || payload.detail || `Erreur HTTP ${response.status}`);
      return renderConnectivity(payload);
    } catch (error) {
      if (lastConnectivityStatus) {
        const preserved = {...lastConnectivityStatus, detail: `${lastConnectivityStatus.detail || ''} Nouvelle vérification impossible : ${error.message}`};
        return renderConnectivity(preserved);
      }
      for (const badge of document.querySelectorAll('[data-connectivity-status], #connectivityBadge')) {
        badge.classList.remove('online', 'offline');
        badge.classList.add('checking');
        badge.innerHTML = '<span aria-hidden="true">●</span> État Internet indéterminé';
        badge.title = error.message;
      }
      return null;
    }
  }

  function startConnectivity({url = '/api/connectivity', intervalMs = 20000} = {}) {
    stopConnectivity();
    connectivityUpdate = () => refreshConnectivity(url);
    connectivityUpdate();
    connectivityTimer = window.setInterval(connectivityUpdate, Math.max(5000, Number(intervalMs) || 20000));
    window.addEventListener('online', connectivityUpdate);
    window.addEventListener('offline', connectivityUpdate);
    return connectivityUpdate;
  }

  function stopConnectivity() {
    if (connectivityTimer !== null) window.clearInterval(connectivityTimer);
    connectivityTimer = null;
    if (connectivityUpdate) {
      window.removeEventListener('online', connectivityUpdate);
      window.removeEventListener('offline', connectivityUpdate);
    }
    connectivityUpdate = null;
  }

  window.PortalUI = {
    initialize,
    bindControls,
    applyTheme,
    applyFont,
    changeFont,
    refreshConnectivity,
    startConnectivity,
    stopConnectivity,
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, {once: true});
  else initialize();
})();
