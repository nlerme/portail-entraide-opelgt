'use strict';

const AnnoncesUI = (() => {
  const sellers = {particulier: 'Particulier', professionnel: 'Professionnel', inconnu: 'Type non précisé'};
  const collator = new Intl.Collator('fr', {numeric: true, sensitivity: 'base'});
  const adHosts = new Set(['www.lesanciennes.com', 'www.leboncoin.fr', 'www.classicnumber.com', 'www.classic-trader.com', 'www.carandclassic.com', 'www.retrocalage.com', 'www.paruvendu.fr', 'www.autoscout24.fr', 'www.carjager.com', 'www.plethorecars.fr', 'dyler.com']);
  const photoHosts = new Set(['assets.lesanciennes.com', 'images.lesanciennes.com', 'www.lesanciennes.com', 'img.leboncoin.fr', 'images.leboncoin.fr', 'www.classicnumber.com', 'classicnumber.com', 'cdn.classic-trader.com', 'assets.carandclassic.com', 'www.retrocalage.com', 'img.paruvendu.fr', 'media.paruvendu.fr', 'prod.pictures.autoscout24.net', 'public.carjager.com', 'www.plethorecars.fr', 'edge.plethorecars.fr', 'assets.dyler.com']);
  const extraAdPaths = Object.fromEntries(Object.entries({"www.carandclassic.com": "/(?:fr/)?(?:voiture|car|la)/C\\d+", "www.retrocalage.com": "/api/annonces/\\d+", "www.paruvendu.fr": "/a/voiture-occasion/opel/gt/\\d+[A-Za-z0-9]+", "www.autoscout24.fr": "/offres/[a-zA-Z0-9_-]+", "www.carjager.com": "/acheter/voiture-[a-z-]+/[a-zA-Z0-9+-]+-CJV[A-Z0-9]+\\.html", "www.plethorecars.fr": "/voiture-collection/[a-zA-Z0-9-]+\\.html", "dyler.com": "/cars/[a-z0-9-]+/[a-z0-9-]+/\\d{4}/\\d+/[a-z0-9-]+"}).map(([host, pattern]) => [host, new RegExp(`^(?:${pattern})$`)]));
  function validUrl(value, photo = false) {
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.username || url.password || url.port || !(photo ? photoHosts : adHosts).has(url.hostname)) return '';
      if (!photo && extraAdPaths[url.hostname]) {
        if (!extraAdPaths[url.hostname].test(url.pathname)) return '';
        if (url.hostname === 'www.retrocalage.com' && url.search !== '?expanded=true') return '';
        return url.href;
      }
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

const AnnoncesFeatures = (() => {
  function matches(item, filter, preferences, lastSeen) {
    if (item.archived && !filter.favoritesOnly) return false;
    if (!filter.showHidden && preferences.hidden.includes(item.id)) return false;
    if (filter.favoritesOnly && !preferences.favorites.includes(item.id)) return false;
    if (filter.newOnly && (item.archived || !item.first_seen_at || Date.parse(item.first_seen_at) <= Date.parse(lastSeen))) return false;
    if (filter.model && item.model !== filter.model) return false;
    if (filter.department && item.department !== filter.department) return false;
    if (filter.min !== null || filter.max !== null) {
      if (typeof item.price !== 'number' || !Number.isFinite(item.price) || (item.currency || 'EUR') !== 'EUR') return false;
      if (filter.min !== null && item.price < filter.min) return false;
      if (filter.max !== null && item.price > filter.max) return false;
    }
    return true;
  }
  function groupItems(items, enabled) {
    const groups = [];
    const town = item => (item.location || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');
    const alike = (a, b) => a.source_id !== b.source_id && ['1100', '1900', 'GT/J'].includes(a.model) && a.model === b.model &&
      a.year && a.year === b.year && a.department && a.department === b.department && town(a) && town(a) !== 'lieunonprecise' && town(a) === town(b) &&
      typeof a.price === 'number' && a.price > 0 && a.price === b.price && (a.currency || 'EUR') === (b.currency || 'EUR') && !a.archived && !b.archived;
    for (const item of items) {
      const existing = enabled && groups.find(group => group.every(other => alike(other, item)));
      if (existing) existing.push(item); else groups.push([item]);
    }
    return groups;
  }
  function validGeo(value) {
    return value && typeof value.lat === 'number' && typeof value.lon === 'number' && Number.isFinite(value.lat) &&
      Number.isFinite(value.lon) && Math.abs(value.lat) <= 90 && Math.abs(value.lon) <= 180;
  }
  function defaultSources(sources, configured) {
    const ids = sources.map(source => source.id);
    return Array.isArray(configured) ? ids.filter(id => configured.includes(id)) : ids;
  }
  return {matches, groupItems, validGeo, defaultSources};
})();
Object.assign(AnnoncesUI, AnnoncesFeatures);
if (typeof module !== 'undefined') module.exports = AnnoncesUI;

if (typeof document !== 'undefined') {
  const el = id => document.getElementById(id);
  const sourceIds = ['lesanciennes', 'leboncoin', 'classicnumber', 'classictrader', 'carandclassic', 'retrocalage', 'paruvendu', 'autoscout24', 'carjager', 'plethorecars', 'dyler'];
  const state = {payload: null, selected: null, sort: 'published_at', direction: -1, csrf: '', active: true,
    fetching: false, timer: null, lastSeen: null, visited: false, itemSignature: '', rows: [], map: null, layer: null,
    mapVisible: false, mapSignature: '', markers: [], bounds: [], cardById: new Map(), prefsBusy: false};
  const labels = {seller_type: 'Type de vendeur', model: 'Modèle', year: 'Année', published_at: 'Date de l’annonce', department: 'Lieu (département)'};
  const sourceClass = item => `source-${sourceIds.includes(item.source_id || item.id) ? (item.source_id || item.id) : 'unknown'}`;
  const prefs = () => state.payload?.preferences || {favorites: [], hidden: []};
  const isNew = item => Boolean(!item.archived && item.first_seen_at && Date.parse(item.first_seen_at) > Date.parse(state.lastSeen));
  function node(tag, className, content) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (content !== undefined) result.textContent = content;
    return result;
  }
  function button(label, action, className = '') {
    const value = node('button', className, label); value.type = 'button'; value.addEventListener('click', action); return value;
  }
  function link(label, url) {
    const value = node('a', '', label); value.href = url; value.target = '_blank'; value.rel = 'noopener noreferrer'; return value;
  }
  function modelName(item) {
    return item.model === 'GT/J' ? 'Opel GT/J' : (['1100', '1900'].includes(item.model) ? `Opel GT ${item.model}` : 'Opel GT — modèle non précisé');
  }
  function dateTime(value) {
    if (!value) return 'jamais';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'non précisée' : new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', dateStyle: 'short', timeStyle: 'short'}).format(date);
  }
  function message(text, error = false) {
    el('actionNotice').textContent = text; el('actionNotice').classList.remove('hidden'); el('actionNotice').classList.toggle('error', error);
  }
  function stop() { state.active = false; window.clearTimeout(state.timer); }
  function clearPrivateContent() {
    state.payload = null; state.rows = []; state.itemSignature = ''; state.mapSignature = '';
    el('annoncesList').replaceChildren(); el('unlocatedAds').replaceChildren(); el('sourceChoices').replaceChildren();
    if (state.map) { state.map.remove(); state.map = null; state.layer = null; }
  }
  async function requestJson(url, options = {}) {
    const headers = {...options.headers};
    if (options.method === 'POST') { headers['X-CSRF-Token'] = state.csrf; headers['Content-Type'] = 'application/json'; }
    const response = await fetch(url, {...options, headers, credentials: 'include', cache: 'no-store'});
    if (response.status === 401) {
      stop(); clearPrivateContent(); window.SessionLifecycle.stop(); window.location.replace('/'); throw new Error('Session expirée.');
    }
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || payload.detail || `Erreur HTTP ${response.status}`);
    return payload;
  }
  let preferenceQueue = Promise.resolve();
  function savePrefs(patch, options = {}) {
    const result = preferenceQueue.then(() => writePrefs(patch, options));
    preferenceQueue = result.catch(() => false);
    return result;
  }
  async function writePrefs(patch, {quiet = false} = {}) {
    state.prefsBusy = true;
    try {
      const result = await requestJson('/api/annonces/preferences', {method: 'POST', body: JSON.stringify(patch)});
      if (!state.active || !state.payload) return false;
      state.payload.preferences = result.preferences;
      if (patch.mark_seen && !quiet) state.lastSeen = result.preferences.last_seen_at;
      renderItems(); renderNtfy();
      return true;
    } catch (error) { message(error.message, true); return false; }
    finally { state.prefsBusy = false; }
  }
  function actions(item) {
    const value = node('div', 'annonce-actions');
    const favorite = prefs().favorites.includes(item.id), hidden = prefs().hidden.includes(item.id);
    const star = button(favorite ? '★ Favori' : '☆ Favori', () => savePrefs({id: item.id, favorite: !favorite}));
    star.setAttribute('aria-pressed', String(favorite)); star.setAttribute('aria-label', `${favorite ? 'Retirer des' : 'Ajouter aux'} favoris l’annonce ${item.number}`);
    const hide = button(hidden ? 'Réafficher' : 'Masquer', () => savePrefs({id: item.id, hidden: !hidden}));
    hide.setAttribute('aria-label', `${hidden ? 'Réafficher' : 'Masquer'} l’annonce ${item.number}`);
    value.append(star, hide); return value;
  }
  function details(item) {
    const value = node('dl');
    for (const [name, text] of [
      ['Prix', AnnoncesUI.formatPrice(item)], ['Année', item.year || 'Non précisée'],
      ['Lieu', `${item.location || 'Non précisé'}${item.department ? ` (${item.department})` : ''}`],
      ['Mise en ligne', AnnoncesUI.formatDate(item.published_at)],
    ]) value.append(node('dt', '', name), node('dd', '', text));
    return value;
  }
  function card(group) {
    const item = group[0], href = AnnoncesUI.validUrl(item.url);
    if (!href) return null;
    const article = node('article', `annonce-card ${sourceClass(item)}`); article.id = `annonce-${item.number}`;
    const photo = link('', href); photo.className = 'annonce-photo'; photo.setAttribute('aria-label', `Voir l’annonce ${item.number} : ${modelName(item)}`);
    const photoUrl = AnnoncesUI.validUrl(item.image_url, true);
    if (photoUrl) {
      const image = node('img'); image.src = photoUrl; image.alt = item.title || 'Opel GT'; image.loading = 'lazy';
      image.width = 640; image.height = 480; image.referrerPolicy = 'no-referrer';
      image.addEventListener('error', () => photo.replaceChildren(node('span', '', 'Photo indisponible')), {once: true}); photo.append(image);
    } else photo.append(node('span', '', 'Photo non fournie'));
    const copy = node('div', 'annonce-copy'), badges = node('div', 'annonce-badges');
    badges.append(node('span', 'source-badge', `#${item.number} · ${item.source_name || ''}`), node('span', '', AnnoncesUI.sellers[item.seller_type] || AnnoncesUI.sellers.inconnu));
    if (isNew(item)) badges.append(node('span', 'new-badge', 'Nouvelle'));
    if (prefs().hidden.includes(item.id)) badges.append(node('span', '', 'Masquée'));
    const title = node('h3'); title.append(link(modelName(item), href)); copy.append(badges, title, details(item));
    if (item.archived) copy.append(node('p', 'stale-label', 'Favori non retrouvé lors de la dernière collecte complète. Sa disponibilité reste à vérifier.'));
    else if (item.observed_at) copy.append(node('p', 'observation-date', `Dernière observation : ${dateTime(item.observed_at)}`));
    const status = state.payload.sources.find(source => source.id === item.source_id);
    if (!item.archived && status && status.status !== 'ok') copy.append(node('p', 'stale-label', 'Source à revérifier : cette annonce peut ne plus être disponible.'));
    const change = item.price_change;
    if (change && Number.isFinite(change.delta)) copy.append(node('p', change.delta < 0 ? 'price-drop' : 'price-rise',
      `${change.delta < 0 ? 'Baisse' : 'Hausse'} de ${AnnoncesUI.formatPrice({price: Math.abs(change.delta), currency: item.currency})} constatée le ${AnnoncesUI.formatDate(change.at)}.`));
    if (item.price_history?.length > 1) {
      const history = node('details', 'price-history'); history.append(node('summary', '', 'Historique des prix'));
      const list = node('ul');
      for (const value of [...item.price_history].reverse()) list.append(node('li', '', `${dateTime(value.at)} : ${AnnoncesUI.formatPrice(value)}`));
      history.append(list); copy.append(history);
    }
    copy.append(actions(item));
    if (group.length > 1) {
      const duplicates = node('details', 'duplicates'); duplicates.open = true;
      duplicates.append(node('summary', '', `${group.length} annonces · doublon possible`), node('p', 'muted', 'Modèle, année, commune et prix identiques. Vérifiez qu’il s’agit du même véhicule.'));
      for (const related of group.slice(1)) {
        const row = node('div', `duplicate-row ${sourceClass(related)}`);
        row.append(link(`#${related.number} · ${related.source_name} · ${AnnoncesUI.formatPrice(related)}`, AnnoncesUI.validUrl(related.url)), actions(related)); duplicates.append(row);
      }
      copy.append(duplicates);
    }
    const bottom = link('Voir l’annonce ↗', href); bottom.className = 'annonce-link-label'; copy.append(bottom);
    article.append(photo, copy);
    article.addEventListener('click', event => {
      if (!event.target.closest('a,button,details,input,select')) window.open(href, '_blank', 'noopener,noreferrer');
    });
    for (const value of group) state.cardById.set(value.id, article);
    return article;
  }
  function filters() {
    return {min: el('minPrice').value === '' ? null : Number(el('minPrice').value), max: el('maxPrice').value === '' ? null : Number(el('maxPrice').value),
      model: el('modelFilter').value, department: el('departmentFilter').value, newOnly: el('newOnly').checked,
      favoritesOnly: el('favoritesOnly').checked, showHidden: el('showHidden').checked};
  }
  function renderItems() {
    if (!state.payload) return;
    state.cardById.clear();
    const options = filters();
    const rows = AnnoncesUI.sortItems(state.payload.items.filter(item => state.selected.has(item.source_id) &&
      AnnoncesUI.matches(item, options, prefs(), state.lastSeen) && AnnoncesUI.validUrl(item.url)), state.sort, state.direction);
    state.rows = rows;
    const groups = AnnoncesUI.groupItems(rows, el('groupDuplicates').checked);
    el('annoncesList').replaceChildren();
    for (const group of groups) { const value = card(group); if (value) el('annoncesList').append(value); }
    const cars = groups.length !== rows.length ? ` · ${groups.length} groupe(s)` : '';
    el('resultCount').textContent = `${rows.length} annonce(s)${cars}`;
    el('emptyState').textContent = state.payload.running && !state.payload.items.length ? 'Première collecte en cours : les résultats apparaîtront source par source.' : 'Aucune annonce ne correspond aux filtres sélectionnés.';
    el('emptyState').classList.toggle('hidden', rows.length !== 0);
    el('annoncesContent').classList.remove('hidden'); el('annoncesContent').setAttribute('aria-busy', 'false');
    el('sources').disabled = false;
    el('newHint').textContent = `${state.payload.items.filter(isNew).length} nouveauté(s) depuis le ${dateTime(state.lastSeen)}.`;
    document.querySelectorAll('[data-sort]').forEach(value => {
      value.disabled = false; const selected = value.dataset.sort === state.sort;
      value.setAttribute('aria-pressed', String(selected)); value.textContent = labels[value.dataset.sort] + (selected ? (state.direction === 1 ? ' ↑' : ' ↓') : '');
    });
    renderMap();
  }
  function renderSources() {
    const progressLabels = {pending: 'En attente', running: 'Collecte en cours', ok: 'Collecte terminée', failed: 'Échec', restricted: 'Accès restreint', missing: 'Jamais collectée'};
    for (const source of state.payload.sources) {
      let choice = el(`source-${source.id}`);
      if (!choice) {
        choice = node('label', `source-choice ${sourceClass(source)}`); choice.id = `source-${source.id}`;
        const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.value = source.id; checkbox.checked = state.selected.has(source.id);
        checkbox.addEventListener('change', () => { if (checkbox.checked) state.selected.add(source.id); else state.selected.delete(source.id); renderItems(); });
        choice.append(checkbox, node('span', 'source-name'), node('span', 'source-detail')); el('sourceChoices').append(choice);
        try {
          const url = new URL(source.url);
          const hosts = {'lesanciennes': 'www.lesanciennes.com', 'leboncoin': 'www.leboncoin.fr', 'classicnumber': 'www.classicnumber.com', 'classictrader': 'www.classic-trader.com', 'carandclassic': 'www.carandclassic.com', 'retrocalage': 'www.retrocalage.com', 'paruvendu': 'www.paruvendu.fr', 'autoscout24': 'www.autoscout24.fr', 'carjager': 'www.carjager.com', 'plethorecars': 'www.plethorecars.fr', 'dyler': 'dyler.com'};
          if (source.id !== 'leboncoin' && url.protocol === 'https:' && url.hostname === hosts[source.id] && !url.username && !url.password && !url.port) {
            const search = link('Ouvrir la recherche ↗', url.href); search.className = 'source-search'; choice.append(search);
          }
        } catch { /* A missing search link must never prevent filtering. */ }
      }
      choice.querySelector('.source-name').textContent = `${source.name} — ${source.count} annonce(s)`;
      const status = state.payload.progress[source.id] || source.status;
      choice.classList.toggle('is-warning', ['failed', 'restricted', 'missing'].includes(status));
      choice.querySelector('.source-detail').textContent = `${progressLabels[status] || status}. ${source.message || ''} Dernier essai : ${dateTime(source.last_attempt_at)}. Dernière réussite complète : ${dateTime(source.last_success_at)}.`;
    }
    el('updateNotice').classList.toggle('hidden', !state.payload.running);
    const finished = Object.values(state.payload.progress).filter(value => !['pending', 'running'].includes(value)).length;
    el('updateNotice').textContent = `Actualisation en cours : ${finished}/${state.payload.sources.length} source(s) traitée(s). Les annonces restent consultables.`;
    el('lastUpdate').textContent = state.payload.last_completed_at ? `Dernière vérification terminée : ${dateTime(state.payload.last_completed_at)}.` : 'Première collecte en attente.';
    const remaining = Math.max(0, Math.ceil((state.payload.next_refresh_at * 1000 - Date.now()) / 60000));
    el('refreshAds').disabled = state.payload.running || remaining > 0;
    el('refreshAds').textContent = state.payload.running ? 'Actualisation en cours…' : 'Actualiser';
    el('refreshHint').textContent = remaining ? `Prochaine actualisation manuelle dans ${remaining} min.` : 'Une actualisation manuelle toutes les 30 minutes. La collecte automatique reste quotidienne à 2 h.';
    const departments = [...new Set(state.payload.items.map(item => item.department).filter(Boolean))].sort();
    const current = el('departmentFilter').value;
    el('departmentFilter').replaceChildren(node('option', '', 'Tous les départements')); el('departmentFilter').firstChild.value = '';
    for (const value of departments) { const option = node('option', '', value); option.value = value; el('departmentFilter').append(option); }
    el('departmentFilter').value = departments.includes(current) ? current : '';
  }
  function renderNtfy() {
    el('notifyNew').checked = Boolean(prefs().notify_new); el('notifyDrops').checked = Boolean(prefs().notify_drops);
    el('ntfyStatus').textContent = state.payload.ntfy_enabled ? 'ntfy est activé. Choisissez les changements à inclure dans le résumé commun.' : 'ntfy n’est pas activé. L’administrateur peut le configurer dans l’onglet Notifications. Vos choix seront conservés.';
  }
  function popup(item) {
    const box = node('div', 'ad-map-popup');
    box.append(node('strong', `source-badge ${sourceClass(item)}`, `#${item.number} · ${item.source_name}`), node('h3', '', modelName(item)),
      node('p', '', AnnoncesUI.sellers[item.seller_type] || AnnoncesUI.sellers.inconnu), details(item), node('p', 'muted', item.geo.label || 'Centre de la commune'));
    if (item.archived) box.append(node('p', '', 'Favori non retrouvé : disponibilité à vérifier.'));
    const href = AnnoncesUI.validUrl(item.url); if (href) box.append(link('Voir l’annonce ↗', href));
    box.append(button('Retrouver dans la liste', () => {
      const article = state.cardById.get(item.id); article?.scrollIntoView({behavior: 'smooth', block: 'center'}); article?.querySelector('a')?.focus({preventScroll: true});
    }));
    return box;
  }
  function fitMap() {
    if (state.map && state.bounds.length) state.map.fitBounds(state.bounds, {padding: [90, 50], maxZoom: 11});
  }
  function renderMap() {
    const located = state.rows.filter(item => AnnoncesUI.validGeo(item.geo));
    const unlocated = state.rows.filter(item => !AnnoncesUI.validGeo(item.geo));
    el('mapStatus').textContent = `${located.length}/${state.rows.length} annonce(s) localisée(s).${unlocated.length ? ' Les lieux absents ou ambigus ne sont pas positionnés.' : ''}`;
    el('unlocatedAds').replaceChildren();
    for (const item of unlocated) el('unlocatedAds').append(button(`#${item.number} · ${item.location || 'Lieu non précisé'}`, () => state.cardById.get(item.id)?.scrollIntoView({behavior: 'smooth', block: 'center'})));
    el('mapLegend').replaceChildren();
    for (const source of state.payload.sources) el('mapLegend').append(node('span', `source-badge ${sourceClass(source)}`, source.name));
    if (!state.mapVisible || !window.L) return;
    if (!state.map) {
      state.map = L.map('annoncesMap', {scrollWheelZoom: false}).setView([46.6, 2.4], 5);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, referrerPolicy: 'strict-origin-when-cross-origin',
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>'}).addTo(state.map)
        .on('tileerror', () => { el('mapStatus').textContent = 'Fond de carte indisponible. Les repères et les annonces restent consultables.'; });
      state.layer = L.layerGroup().addTo(state.map);
    }
    const signature = JSON.stringify(located);
    if (signature === state.mapSignature) return;
    state.mapSignature = signature; state.layer.clearLayers(); state.bounds = [];
    const positions = new Map();
    for (const item of located) {
      const key = `${item.geo.lat},${item.geo.lon}`;
      if (!positions.has(key)) positions.set(key, []); positions.get(key).push(item);
    }
    for (const group of positions.values()) {
      const position = [group[0].geo.lat, group[0].geo.lon], holder = node('div', 'map-number-group');
      for (const item of group) {
        const marker = button(String(item.number), event => {
          L.DomEvent.stopPropagation(event);
          L.popup({maxWidth: Math.min(300, state.map.getSize().x - 70), maxHeight: Math.min(330, state.map.getSize().y - 70),
            autoPanPadding: [15, 15]}).setLatLng(position).setContent(popup(item)).openOn(state.map);
        }, `map-number ${sourceClass(item)}`);
        marker.setAttribute('aria-label', `Annonce ${item.number}, ${item.source_name}, ${item.location}`); holder.append(marker);
      }
      const columns = Math.min(4, group.length), width = columns * 39 - 3, height = Math.ceil(group.length / columns) * 39 - 3;
      holder.style.gridTemplateColumns = `repeat(${columns},max-content)`;
      L.marker(position, {keyboard: false, icon: L.divIcon({html: holder, className: 'ad-map-icon',
        iconSize: [width, height], iconAnchor: [width / 2, height / 2]})}).addTo(state.layer);
      state.bounds.push(position);
    }
    state.map.invalidateSize(); fitMap();
  }
  async function refresh() {
    if (!state.active || state.fetching) return;
    state.fetching = true; window.clearTimeout(state.timer);
    try {
      const payload = await requestJson('/api/annonces');
      if (!state.active) return;
      if (typeof payload.running !== 'boolean' || !Array.isArray(payload.sources) || !Array.isArray(payload.items)) throw new Error('État des annonces indisponible.');
      payload.progress ||= {}; payload.preferences ||= {favorites: [], hidden: []};
      // Existing caches acquire persistent numbers on their next collection.
      const numbers = new Set(payload.items.filter(item => item.number).map(item => item.number)); let next = Math.max(0, ...numbers) + 1;
      for (const item of [...payload.items].sort((a, b) => String(a.id).localeCompare(String(b.id)))) { if (!item.number) item.number = next++; }
      state.payload = payload;
      if (state.selected === null) state.selected = new Set(AnnoncesUI.defaultSources(payload.sources, payload.default_enabled_sources));
      if (!state.lastSeen) state.lastSeen = payload.preferences.last_seen_at || new Date(Date.now() - 86400000).toISOString();
      el('errorNotice').classList.add('hidden'); renderSources(); renderNtfy();
      const signature = JSON.stringify([payload.items, payload.preferences, payload.sources.map(source => source.status)]);
      if (signature !== state.itemSignature) { state.itemSignature = signature; renderItems(); }
      if (!state.visited) { state.visited = true; await savePrefs({mark_seen: true}, {quiet: true}); }
    } catch (error) {
      el('errorNotice').textContent = `${error.message} ${state.payload ? 'Les dernières annonces affichées restent consultables.' : ''}`;
      el('errorNotice').classList.remove('hidden');
    } finally { state.fetching = false; if (state.active) state.timer = window.setTimeout(refresh, state.payload?.running ? 2000 : 15000); }
  }
  document.querySelectorAll('[data-sort]').forEach(value => value.addEventListener('click', () => {
    if (value.dataset.sort === state.sort) state.direction *= -1;
    else { state.sort = value.dataset.sort; state.direction = ['year', 'published_at'].includes(state.sort) ? -1 : 1; } renderItems();
  }));
  for (const id of ['minPrice', 'maxPrice', 'modelFilter', 'departmentFilter', 'newOnly', 'favoritesOnly', 'showHidden', 'groupDuplicates']) el(id).addEventListener(id.includes('Price') ? 'input' : 'change', renderItems);
  el('resetFilters').addEventListener('click', () => {
    if (!state.payload) return;
    for (const id of ['minPrice', 'maxPrice', 'modelFilter', 'departmentFilter']) el(id).value = '';
    for (const id of ['newOnly', 'favoritesOnly', 'showHidden']) el(id).checked = false;
    el('groupDuplicates').checked = true;
    state.selected = new Set(AnnoncesUI.defaultSources(state.payload.sources, state.payload.default_enabled_sources));
    document.querySelectorAll('#sourceChoices input').forEach(value => { value.checked = state.selected.has(value.value); }); renderItems();
  });
  el('markSeen').addEventListener('click', async () => { if (await savePrefs({mark_seen: true})) message('Les annonces sont marquées comme vues.'); });
  for (const [id, key] of [['notifyNew', 'notify_new'], ['notifyDrops', 'notify_drops']]) el(id).addEventListener('change', async () => {
    const saved = await savePrefs({[key]: el(id).checked}); if (!saved) renderNtfy();
  });
  el('refreshAds').addEventListener('click', async () => {
    el('refreshAds').disabled = true;
    try { const result = await requestJson('/api/annonces/refresh', {method: 'POST', body: '{}'}); message(result.message); await refresh(); }
    catch (error) { message(error.message, true); renderSources(); }
  });
  el('fitMap').addEventListener('click', fitMap);
  const observer = typeof IntersectionObserver === 'function' ? new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) { state.mapVisible = true; if (state.payload) renderMap(); observer.disconnect(); }
  }) : null;
  if (observer) observer.observe(el('annoncesMap')); else state.mapVisible = true;
  el('logout').addEventListener('click', async () => {
    stop(); clearPrivateContent(); window.SessionTimer.stop(); window.SessionLifecycle.stop(); window.PortalUI.stopConnectivity();
    try { await requestJson('/api/logout', {method: 'POST'}); } catch {} window.location.replace('/');
  });
  window.addEventListener('pagehide', () => { stop(); clearPrivateContent(); });
  window.addEventListener('pageshow', event => { if (event.persisted) { state.active = true; refresh(); } });
  async function initialize() {
    const session = await requestJson('/api/session'); if (!session.authenticated) { stop(); window.location.replace('/'); return; }
    state.csrf = session.csrfToken || '';
    window.SessionTimer.start({expiresAt: session.expiresAt, serverTime: session.serverTime, durationMinutes: session.durationMinutes,
      element: el('sessionRemaining'), onExpire: () => window.SessionLifecycle.expire()});
    window.SessionLifecycle.start({sessionKind: 'member', token: state.csrf}); window.PortalUI.startConnectivity();
    el('appShell').classList.remove('hidden'); await refresh();
  }
  initialize().catch(error => { el('appShell').classList.remove('hidden'); el('errorNotice').textContent = error.message; el('errorNotice').classList.remove('hidden'); });
}
