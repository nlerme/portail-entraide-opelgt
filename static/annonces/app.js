'use strict';

const AnnoncesUI = (() => {
  const sellers = {particulier: 'Particulier', professionnel: 'Professionnel', inconnu: 'Type non précisé'};
  const collator = new Intl.Collator('fr', {numeric: true, sensitivity: 'base'});
  const adHosts = new Set(['www.lesanciennes.com', 'www.leboncoin.fr', 'www.classicnumber.com', 'www.classic-trader.com']);
  const photoHosts = new Set(['assets.lesanciennes.com', 'images.lesanciennes.com', 'www.lesanciennes.com', 'img.leboncoin.fr', 'images.leboncoin.fr', 'www.classicnumber.com', 'classicnumber.com', 'cdn.classic-trader.com']);
  function validUrl(value, photo = false) {
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.username || url.password || url.port || !(photo ? photoHosts : adHosts).has(url.hostname)) return '';
      if (!photo) {
        const classicNumber = url.hostname === 'www.classicnumber.com' && /^\/[a-z0-9-]+-collection-a-vendre-\d+\.html$/.test(url.pathname);
        const classicTrader = url.hostname === 'www.classic-trader.com' && /^\/fr\/voitures\/annonce\/[a-z0-9/-]+\/\d+$/.test(url.pathname);
        if (!classicNumber && !classicTrader && !/^\/(?:annonce\/|ad\/|[a-z_]+\/\d+\.htm$)/.test(url.pathname)) return '';
      }
      return url.href;
    } catch { return ''; }
  }
  function formatDate(value) {
    if (!value || !/^\d{4}-\d{2}-\d{2}/.test(value)) return 'Non précisée';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Non précisée' : new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris'}).format(date);
  }
  function formatPrice(item) {
    if (typeof item.price === 'number' && Number.isFinite(item.price) && item.price >= 0) {
      const currency = /^[A-Z]{3}$/.test(item.currency || '') ? item.currency : 'EUR';
      return new Intl.NumberFormat('fr-FR', {style: 'currency', currency, maximumFractionDigits: Number.isInteger(item.price) ? 0 : 2}).format(item.price);
    }
    return item.price_label || 'Non précisé';
  }
  function sortItems(items, key = 'published_at', direction = -1) {
    const value = item => {
      if (key === 'seller_type') return {particulier: 0, professionnel: 1}[item.seller_type] ?? null;
      if (key === 'model') return {'1100': 0, '1900': 1, 'GT/J': 2}[item.model] ?? null;
      if (key === 'year') return Number(item.year) || null;
      if (key === 'department') return item.department ? String(item.department).replace('2A', '20A').replace('2B', '20B') : null;
      return item.published_at || null;
    };
    return [...items].sort((a, b) => {
      const left = value(a), right = value(b);
      if (left === null || right === null) return left === right ? collator.compare(a.id || '', b.id || '') : (left === null ? 1 : -1);
      const delta = typeof left === 'number' ? left - right : collator.compare(left, right);
      return delta * direction || collator.compare(a.location || '', b.location || '') || collator.compare(a.id || '', b.id || '');
    });
  }
  return {sellers, validUrl, formatDate, formatPrice, sortItems};
})();
if (typeof module !== 'undefined') module.exports = AnnoncesUI;

if (typeof document !== 'undefined') {
  const element = id => document.getElementById(id);
  const state = {payload: null, selected: null, sort: 'published_at', direction: -1, csrf: '', active: true, fetching: false, timer: null};
  const labels = {seller_type: 'Type de vendeur', model: 'Modèle', year: 'Année', published_at: 'Date de l’annonce', department: 'Lieu (département)'};
  function node(tag, className, content) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (content !== undefined) result.textContent = content;
    return result;
  }
  function stop() {
    state.active = false;
    window.clearTimeout(state.timer);
  }
  async function requestJson(url, options = {}) {
    const headers = {...options.headers};
    if (options.method === 'POST') headers['X-CSRF-Token'] = state.csrf;
    const response = await fetch(url, {...options, headers, credentials: 'include', cache: 'no-store'});
    if (response.status === 401) {
      stop();
      window.SessionLifecycle.stop();
      window.location.replace('/');
      throw new Error('Session expirée.');
    }
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || `Erreur HTTP ${response.status}`);
    return payload;
  }
  function hideItems() {
    element('annoncesList').replaceChildren();
    element('annoncesContent').classList.add('hidden');
    element('annoncesContent').setAttribute('aria-busy', 'true');
    element('sources').disabled = true;
    document.querySelectorAll('[data-sort]').forEach(button => { button.disabled = true; });
  }
  function card(item) {
    const href = AnnoncesUI.validUrl(item.url);
    if (!href) return null;
    const link = node('a', 'annonce-card');
    link.href = href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    const photo = node('div', 'annonce-photo');
    const photoUrl = AnnoncesUI.validUrl(item.image_url, true);
    if (photoUrl) {
      const image = node('img');
      image.src = photoUrl;
      image.alt = item.title || 'Opel GT';
      image.loading = 'lazy';
      image.width = 640;
      image.height = 480;
      image.referrerPolicy = 'no-referrer';
      image.addEventListener('error', () => photo.replaceChildren(node('span', '', 'Photo indisponible')), {once: true});
      photo.append(image);
    } else photo.append(node('span', '', 'Photo non fournie'));
    const copy = node('div', 'annonce-copy');
    const badges = node('div', 'annonce-badges');
    badges.append(node('span', '', item.source_name || ''), node('span', '', '·'), node('span', '', AnnoncesUI.sellers[item.seller_type] || AnnoncesUI.sellers.inconnu));
    const model = item.model === 'GT/J' ? 'Opel GT/J' : (['1100', '1900'].includes(item.model) ? `Opel GT ${item.model}` : 'Opel GT — modèle non précisé');
    copy.append(badges, node('h3', '', model));
    const details = node('dl');
    const fields = [
      ['Prix', AnnoncesUI.formatPrice(item)],
      ['Année', item.year || 'Non précisée'],
      ['Lieu', `${item.location || 'Non précisé'}${item.department ? ` (${item.department})` : ''}`],
      ['Mise en ligne', AnnoncesUI.formatDate(item.published_at)],
    ];
    for (const [name, value] of fields) details.append(node('dt', '', name), node('dd', '', value));
    copy.append(details, node('span', 'annonce-link-label', 'Voir l’annonce ↗'));
    link.append(photo, copy);
    return link;
  }
  function renderItems() {
    if (!state.payload || state.payload.running) { hideItems(); return; }
    element('annoncesList').replaceChildren();
    const rows = AnnoncesUI.sortItems((state.payload.items || []).filter(item => state.selected.has(item.source_id)), state.sort, state.direction);
    let count = 0;
    for (const item of rows) {
      const content = card(item);
      if (content) { element('annoncesList').append(content); count += 1; }
    }
    element('resultCount').textContent = `${count} annonce${count > 1 ? 's' : ''}`;
    element('emptyState').textContent = state.selected.size ? 'Aucune annonce disponible pour les sources sélectionnées. Consultez l’état des sources ci-dessus.' : 'Sélectionnez au moins une source pour afficher les annonces.';
    element('emptyState').classList.toggle('hidden', count !== 0);
    element('annoncesContent').classList.remove('hidden');
    element('annoncesContent').setAttribute('aria-busy', 'false');
    element('sources').disabled = false;
    document.querySelectorAll('[data-sort]').forEach(button => {
      button.disabled = false;
      const selected = button.dataset.sort === state.sort;
      button.setAttribute('aria-pressed', String(selected));
      button.textContent = labels[button.dataset.sort] + (selected ? (state.direction === 1 ? ' ↑' : ' ↓') : '');
    });
  }
  function renderSources(sources) {
    if (state.selected === null) state.selected = new Set(sources.map(source => source.id));
    for (const source of sources) {
      let choice = element(`source-${source.id}`);
      if (!choice) {
        choice = node('label', 'source-choice');
        choice.id = `source-${source.id}`;
        const checkbox = node('input');
        checkbox.type = 'checkbox';
        checkbox.value = source.id;
        checkbox.checked = state.selected.has(source.id);
        checkbox.addEventListener('change', () => {
          if (checkbox.checked) state.selected.add(source.id); else state.selected.delete(source.id);
          renderItems();
        });
        choice.append(checkbox, node('span', 'source-name', source.name), node('span', 'source-detail'));
        element('sourceChoices').append(choice);
      }
      choice.classList.toggle('is-warning', source.status !== 'ok');
      const success = source.last_success_at ? ` Dernière collecte réussie : ${AnnoncesUI.formatDate(source.last_success_at)}.` : '';
      choice.querySelector('.source-detail').textContent = `${source.message || 'Première collecte en attente.'}${success}`;
    }
  }
  async function refresh() {
    if (!state.active || state.fetching) return;
    state.fetching = true;
    window.clearTimeout(state.timer);
    try {
      const payload = await requestJson('/api/annonces');
      if (!state.active) return;
      if (typeof payload.running !== 'boolean' || !Array.isArray(payload.sources) || !Array.isArray(payload.items)) throw new Error('État des annonces indisponible.');
      state.payload = payload;
      renderSources(payload.sources);
      element('errorNotice').classList.add('hidden');
      element('updateNotice').classList.toggle('hidden', !payload.running);
      element('lastUpdate').textContent = payload.last_completed_at ? `Dernière vérification : ${AnnoncesUI.formatDate(payload.last_completed_at)}.` : 'Première collecte en attente.';
      renderItems();
    } catch (error) {
      state.payload = null;
      hideItems();
      element('updateNotice').classList.add('hidden');
      element('errorNotice').textContent = `${error.message} Les annonces seront réaffichées lorsque leur état sera connu.`;
      element('errorNotice').classList.remove('hidden');
    } finally {
      state.fetching = false;
      if (state.active) state.timer = window.setTimeout(refresh, 2000);
    }
  }
  document.querySelectorAll('[data-sort]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.sort === state.sort) state.direction *= -1;
    else { state.sort = button.dataset.sort; state.direction = ['year', 'published_at'].includes(state.sort) ? -1 : 1; }
    renderItems();
  }));
  element('logout').addEventListener('click', async () => {
    stop();
    hideItems();
    window.SessionTimer.stop();
    window.SessionLifecycle.stop();
    window.PortalUI.stopConnectivity();
    try { await requestJson('/api/logout', {method: 'POST'}); } catch {}
    window.location.replace('/');
  });
  window.addEventListener('pagehide', () => { stop(); hideItems(); });
  window.addEventListener('pageshow', event => {
    if (event.persisted) { state.active = true; state.payload = null; hideItems(); refresh(); }
  });
  async function initialize() {
    const session = await requestJson('/api/session');
    if (!session.authenticated) { stop(); window.location.replace('/'); return; }
    state.csrf = session.csrfToken || '';
    window.SessionTimer.start({expiresAt: session.expiresAt, serverTime: session.serverTime, durationMinutes: session.durationMinutes,
      element: element('sessionRemaining'), onExpire: () => window.SessionLifecycle.expire()});
    window.SessionLifecycle.start({sessionKind: 'member', token: state.csrf});
    window.PortalUI.startConnectivity();
    element('appShell').classList.remove('hidden');
    await refresh();
  }
  initialize().catch(error => {
    hideItems();
    element('appShell').classList.remove('hidden');
    element('errorNotice').textContent = error.message;
    element('errorNotice').classList.remove('hidden');
  });
}
