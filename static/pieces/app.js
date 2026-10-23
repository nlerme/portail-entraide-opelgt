'use strict';

const DEFAULT_PAGE_SIZE = 100;
const CONNECTIVITY_INTERVAL_MS = 20000;
const CATALOG_STATUS_INTERVAL_MS = 2500;
const FILTER_STORAGE_KEY = 'opelgt-result-filters-v1';
const state = {
  sites: [],
  offers: [],
  visibleOffers: [],
  suggestions: [],
  ambiguityReasons: [],
  currentPage: 1,
  pageSize: DEFAULT_PAGE_SIZE,
  loading: false,
  connectivityOnline: false,
  connectivityPromise: null,
  sitesLoading: false,
  sitesChecked: false,
  catalogReady: false,
  catalogRunning: false,
  catalogStatusLoaded: false,
  catalogSuppliers: {},
  userTouchedSites: false,
  syncPoll: null,
  currentQuery: '',
  recoveredCatalogCount: 0,
  appInitialized: false,
  connectivityTimer: null,
  csrfToken: '',
};

const els = {
  html: document.documentElement,
  appShell: document.querySelector('#appShell'),
  logoutButton: document.querySelector('#logoutButton'),
  themeButton: document.querySelector('#themeButton'),
  themeIcon: document.querySelector('#themeIcon'),
  themeLabel: document.querySelector('#themeLabel'),
  fontDecrease: document.querySelector('#fontDecrease'),
  fontIncrease: document.querySelector('#fontIncrease'),
  connectivityBadge: document.querySelector('#connectivityBadge'),
  sessionRemaining: document.querySelector('#sessionRemaining'),
  catalogSyncState: document.querySelector('#catalogSyncState'),
  catalogWaitNotice: document.querySelector('#catalogWaitNotice'),
  catalogProgressPanel: document.querySelector('#catalogProgressPanel'),
  catalogGlobalPercent: document.querySelector('#catalogGlobalPercent'),
  catalogGlobalBar: document.querySelector('#catalogGlobalBar'),
  catalogCurrentSupplier: document.querySelector('#catalogCurrentSupplier'),
  catalogSupplierProgress: document.querySelector('#catalogSupplierProgress'),
  lastSyncDate: document.querySelector('#lastSyncDate'),
  selectAllSites: document.querySelector('#selectAllSites'),
  clearAllSites: document.querySelector('#clearAllSites'),
  sitesState: document.querySelector('#sitesState'),
  sitesGrid: document.querySelector('#sitesGrid'),
  searchForm: document.querySelector('#searchForm'),
  keywords: document.querySelector('#keywords'),
  searchButton: document.querySelector('#searchButton'),
  formError: document.querySelector('#formError'),
  progressPanel: document.querySelector('#progressPanel'),
  resultsPanel: document.querySelector('#resultsPanel'),
  resultsSummary: document.querySelector('#resultsSummary'),
  exportCsvButton: document.querySelector('#exportCsvButton'),
  resultsContent: document.querySelector('#resultsContent'),
  suggestionsPanel: document.querySelector('#suggestionsPanel'),
  suggestionsReason: document.querySelector('#suggestionsReason'),
  suggestionList: document.querySelector('#suggestionList'),
  resultsTableWrap: document.querySelector('#resultsTableWrap'),
  resultsControls: document.querySelector('#resultsControls'),
  supplierFilter: document.querySelector('#supplierFilter'),
  priceMin: document.querySelector('#priceMin'),
  priceMax: document.querySelector('#priceMax'),
  availabilityFilter: document.querySelector('#availabilityFilter'),
  sortResults: document.querySelector('#sortResults'),
  pageSize: document.querySelector('#pageSize'),
  resetResultFilters: document.querySelector('#resetResultFilters'),
  filterSummary: document.querySelector('#filterSummary'),
  resultsTableBody: document.querySelector('#resultsTableBody'),
  emptyState: document.querySelector('#emptyState'),
  emptyStateTitle: document.querySelector('#emptyStateTitle'),
  emptyStateText: document.querySelector('#emptyStateText'),
  pagination: document.querySelector('#pagination'),
  prevPage: document.querySelector('#prevPage'),
  nextPage: document.querySelector('#nextPage'),
  pageInfo: document.querySelector('#pageInfo'),
  exampleQueries: [...document.querySelectorAll('.example-query')],
};

function stopApplicationPolling() {
  if (state.syncPoll) {
    window.clearInterval(state.syncPoll);
    state.syncPoll = null;
  }
  if (state.connectivityTimer) {
    window.clearInterval(state.connectivityTimer);
    state.connectivityTimer = null;
  }
}

function showLogin() {
  stopApplicationPolling();
  window.SessionLifecycle.stop();
  window.location.replace('/');
}

function showApplication() {
  els.appShell.classList.remove('hidden');
  if (!state.appInitialized) {
    state.appInitialized = true;
    loadSites(true);
    loadCatalogSyncStatus();
    startSyncPolling();
    state.connectivityTimer = window.setInterval(async () => {
      const wasOnline = state.connectivityOnline;
      const online = await checkConnectivity(true);
      if (online && !wasOnline && !state.sitesLoading) {
        await loadSites(true);
        await loadCatalogSyncStatus();
      }
    }, CONNECTIVITY_INTERVAL_MS);
    validateForm();
  } else {
    startSyncPolling();
  }
}

async function bootstrapAuthentication() {
  try {
    const session = await fetchJson('/api/session', {cache: 'no-store'}, 10000, false);
    if (session.authenticated) {
      state.csrfToken = session.csrfToken || '';
      window.SessionTimer.start({
        expiresAt: session.expiresAt,
        serverTime: session.serverTime,
        durationMinutes: session.durationMinutes,
        element: els.sessionRemaining,
        onExpire: () => window.SessionLifecycle.expire(),
      });
      window.SessionLifecycle.start({sessionKind: 'member', token: state.csrfToken});
      showApplication();
    }
    else window.location.replace('/');
  } catch (error) {
    console.error(error); window.location.replace('/');
  }
}


async function logout() {
  window.SessionTimer.stop();
  window.SessionLifecycle.stop();
  try { await fetchJson('/api/logout', {method: 'POST'}, 10000, false); } catch {}
  state.appInitialized = false;
  state.sites = [];
  state.offers = [];
  window.location.replace('/');
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'}[char]));
}

function safeUrl(value) {
  try {
    const url = new URL(value, window.location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '#';
  } catch { return '#'; }
}

function setDisabled(control, disabled) {
  control.disabled = Boolean(disabled);
  control.setAttribute('aria-disabled', String(Boolean(disabled)));
}

function alignResultsPanel() {
  // The same form submit event is used by Enter and by the comparison button.
  // Waiting for the next frame ensures the progress/result block is visible
  // before aligning its top with the viewport on every browser and platform.
  window.requestAnimationFrame(() => {
    els.resultsPanel.scrollIntoView({behavior: 'smooth', block: 'start'});
  });
}

async function fetchJson(url, options = {}, timeoutMs = 30000, handleUnauthorized = true) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = {...(options.headers || {})};
    const method = String(options.method || 'GET').toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && state.csrfToken) headers['X-CSRF-Token'] = state.csrfToken;
    const response = await fetch(url, {...options, headers, signal: controller.signal});
    let payload = null;
    try { payload = await response.json(); } catch { /* réponse non JSON */ }
    if (!response.ok) {
      const detail = payload?.message || payload?.detail || `Erreur HTTP ${response.status}`;
      const message = typeof detail === 'string' ? detail : JSON.stringify(detail);
      if (response.status === 401 && handleUnauthorized) showLogin(message);
      throw new Error(message);
    }
    return payload;
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error(`Le serveur n'a pas répondu dans le délai imparti (${Math.round(timeoutMs / 1000)} s).`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function renderConnectivity(online, detail = '', conclusive = true) {
  const confirmedOnline = Boolean(online);
  const isConclusive = conclusive !== false;
  state.connectivityOnline = confirmedOnline || !isConclusive;
  els.connectivityBadge.classList.remove('checking', 'online', 'offline');
  if (!isConclusive && !confirmedOnline) {
    els.connectivityBadge.classList.add('checking');
    els.connectivityBadge.innerHTML = '<span aria-hidden="true">●</span> Vérification Internet…';
  } else {
    els.connectivityBadge.classList.add(confirmedOnline ? 'online' : 'offline');
    els.connectivityBadge.innerHTML = `<span aria-hidden="true">●</span> ${confirmedOnline ? 'Internet disponible' : 'Internet indisponible'}`;
  }
  els.connectivityBadge.title = detail;
  validateForm();
}

async function checkConnectivity(force = false) {
  if (state.connectivityPromise) return state.connectivityPromise;
  state.connectivityPromise = (async () => {
    els.connectivityBadge.classList.remove('online', 'offline');
    els.connectivityBadge.classList.add('checking');
    els.connectivityBadge.innerHTML = '<span aria-hidden="true">●</span> Vérification Internet…';
    try {
      const status = await fetchJson(
        `/api/pieces/connectivity?force=${force ? 'true' : 'false'}`,
        {cache: 'no-store'},
        12000,
      );
      renderConnectivity(status.online, status.detail, status.conclusive);
      return status.online || status.conclusive === false;
    } catch (error) {
      els.connectivityBadge.classList.remove('online', 'offline');
      els.connectivityBadge.classList.add('checking');
      els.connectivityBadge.innerHTML = '<span aria-hidden="true">●</span> État Internet indéterminé';
      els.connectivityBadge.title = error.message;
      return state.connectivityOnline;
    }
  })();
  try {
    return await state.connectivityPromise;
  } finally {
    state.connectivityPromise = null;
  }
}

async function loadSites(force = false) {
  if (state.sitesLoading) return;
  state.sitesLoading = true;
  state.sitesChecked = false;
  els.searchButton.disabled = true;
  els.sitesGrid.setAttribute('aria-busy', 'true');
  els.sitesState.classList.remove('hidden');
  els.sitesState.classList.add('sites-state-checking');
  els.sitesState.innerHTML = '<span class="spinner" aria-hidden="true"></span><strong>Vérification de la disponibilité des boutiques…</strong><span>Merci de patienter quelques secondes.</span>';
  try {
    const online = await checkConnectivity(force);
    if (!online) {
      state.sites = [];
      els.sitesGrid.innerHTML = '';
      els.sitesState.textContent = 'Connexion Internet indisponible : la recherche reste désactivée.';
      return;
    }

    state.sites = await fetchJson(
      `/api/pieces/sites?force=${force ? 'true' : 'false'}`,
      {cache: 'no-store'},
      30000,
    );
    renderSites();
    const onlineCount = state.sites.filter(site => site.online).length;
    els.sitesState.textContent = onlineCount > 0
      ? `${onlineCount} boutique${onlineCount > 1 ? 's' : ''} joignable${onlineCount > 1 ? 's' : ''} sur ${state.sites.length}. La sélection dépend ensuite du catalogue local synchronisé.`
      : `Les contrôles préalables n’ont confirmé aucune boutique. Les fournisseurs resteront désactivés si leur catalogue local n’est pas utilisable.`;
  } catch (error) {
    state.sites = [];
    els.sitesGrid.innerHTML = '';
    els.sitesState.textContent = `Contrôle terminé sans résultat exploitable : ${error.message}`;
  } finally {
    state.sitesChecked = true;
    state.sitesLoading = false;
    els.sitesGrid.setAttribute('aria-busy', 'false');
    els.sitesState.classList.remove('sites-state-checking');
    validateForm();
  }
}

function syncSupplier(siteId) {
  return state.catalogSuppliers?.[siteId] || null;
}

function supplierCatalogUsable(siteId) {
  const supplier = syncSupplier(siteId);
  return Boolean(supplier?.ok && Number(supplier.item_count || 0) > 0);
}

function hasAtLeastOneRecoveredCatalog() {
  return state.recoveredCatalogCount > 0;
}

function supplierCatalogDetail(siteId) {
  const supplier = syncSupplier(siteId);
  if (!state.catalogStatusLoaded) return 'Catalogue : statut non chargé.';
  if (!supplier) return 'Catalogue : fournisseur absent du statut de synchronisation.';
  const count = Number(supplier.item_count || 0);
  if (supplier.ok && count > 0) return `Catalogue : ${count} pièce${count > 1 ? 's' : ''} synchronisée${count > 1 ? 's' : ''}.`;
  if (supplier.status === 'running') return 'Catalogue : synchronisation en cours.';
  if (supplier.status === 'pending') return 'Catalogue : en attente de synchronisation.';
  return `Catalogue indisponible : ${supplier.message || supplier.status || 'non récupérable'}.`;
}

function supplierCatalogBadge(site) {
  const supplier = syncSupplier(site.id);
  const catalogUsable = supplierCatalogUsable(site.id);
  const webStatus = `Site web : ${site.badge || 'statut inconnu'}${site.detail ? ` — ${site.detail}` : ''}`;

  if (!state.catalogStatusLoaded) {
    return {className: site.online ? 'online' : 'offline', label: site.badge || 'statut', detail: `Catalogue : statut non chargé. ${webStatus}`};
  }
  if (catalogUsable) {
    return {className: 'online', label: 'catalogue prêt', detail: `${supplierCatalogDetail(site.id)} ${webStatus}`};
  }
  if (state.catalogRunning && supplier?.status === 'running') {
    return {className: 'pending', label: 'mise à jour', detail: `${supplierCatalogDetail(site.id)} ${webStatus}`};
  }
  if (state.catalogRunning && supplier?.status === 'pending') {
    return {className: 'pending', label: 'en attente', detail: `${supplierCatalogDetail(site.id)} ${webStatus}`};
  }
  return {className: 'offline', label: 'catalogue absent', detail: `${supplierCatalogDetail(site.id)} ${webStatus}`};
}

function selectedSitesHaveReadyCatalogs() {
  const selected = selectedValues('site');
  return selected.length > 0 && selected.every(siteId => supplierCatalogUsable(siteId));
}

function renderSites() {
  const previouslyChecked = new Set(selectedValues('site'));
  els.sitesGrid.innerHTML = state.sites.map(site => {
    const catalogUsable = supplierCatalogUsable(site.id);
    const disabled = !catalogUsable ? 'disabled aria-disabled="true"' : '';
    const shouldCheck = catalogUsable && (state.userTouchedSites ? previouslyChecked.has(site.id) : site.default_enabled !== false);
    const checked = shouldCheck ? 'checked' : '';
    const badge = supplierCatalogBadge(site);
    const cardClass = disabled ? 'choice-card site-card disabled-choice' : 'choice-card site-card';
    const webDetail = `${site.badge || 'statut inconnu'}${site.detail ? ` — ${site.detail}` : ''}${site.response_ms ? ` · ${site.response_ms} ms` : ''}`;
    return `
      <label class="${cardClass}" title="${escapeHtml(badge.detail)}">
        <input type="checkbox" name="site" value="${escapeHtml(site.id)}" ${checked} ${disabled}>
        <span class="choice-check" aria-hidden="true">✓</span>
        <span class="site-copy">
          <span class="site-topline">
            <strong>${escapeHtml(site.name)}</strong>
            <span class="badge ${badge.className}">${escapeHtml(badge.label)}</span>
          </span>
          <span class="site-detail">${escapeHtml(supplierCatalogDetail(site.id))}<br>${escapeHtml(`Site web : ${webDetail}`)}</span>
        </span>
      </label>`;
  }).join('');
  els.sitesGrid.querySelectorAll('input').forEach(input => input.addEventListener('change', () => {
    state.userTouchedSites = true;
    validateForm();
  }));
}


function formatSyncDate(value) {
  if (!value) return 'jamais';
  try {
    return new Intl.DateTimeFormat('fr-FR', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function renderCatalogSync(status) {
  const suppliers = status?.suppliers || [];
  state.catalogStatusLoaded = Boolean(status);
  state.catalogSuppliers = Object.fromEntries(suppliers.map(supplier => [supplier.site_id, supplier]));
  state.catalogRunning = Boolean(status?.running || status?.queued);
  const okCount = suppliers.filter(supplier => supplier.ok && Number(supplier.item_count || 0) > 0).length;
  state.recoveredCatalogCount = okCount;
  const totalCount = suppliers.length || state.sites.length || 0;
  const completedCount = suppliers.filter(supplier => !['pending', 'running'].includes(supplier.status)).length;
  state.catalogReady = okCount > 0;
  const lastSync = status?.last_completed_at || status?.last_success_at || status?.finished_at || null;
  const failedCount = suppliers.filter(supplier => ['failed', 'unavailable'].includes(supplier.status)).length;
  const detail = status?.detail || 'Statut des catalogues indisponible.';

  els.lastSyncDate.textContent = `Dernière synchronisation : ${formatSyncDate(lastSync)}`;
  els.catalogSyncState.textContent = state.catalogRunning
    ? `Synchronisation en cours : ${completedCount}/${totalCount} fournisseur${totalCount > 1 ? 's' : ''} traité${completedCount > 1 ? 's' : ''}. La recherche est temporairement désactivée.`
    : state.catalogReady
      ? `Synchronisation terminée : ${okCount}/${totalCount} catalogue${totalCount > 1 ? 's' : ''} utilisable${okCount > 1 ? 's' : ''}${failedCount ? `, ${failedCount} indisponible${failedCount > 1 ? 's' : ''}` : ''}.`
      : `Synchronisation indisponible : ${detail}`;
  els.catalogWaitNotice.classList.toggle('hidden', !state.catalogRunning);
  if (state.catalogRunning) {
    els.catalogWaitNotice.textContent = `${detail} La recherche est temporairement désactivée jusqu’à la fin du traitement.`;
  }
  renderCatalogProgress(status, suppliers);

  const supplierSelectionLocked = !state.catalogReady || state.catalogRunning;
  setDisabled(els.selectAllSites, supplierSelectionLocked);
  setDisabled(els.clearAllSites, supplierSelectionLocked);

  if (state.sites.length) renderSites();
  validateForm();
}


function renderCatalogProgress(status, suppliers) {
  const running = Boolean(status?.running || status?.queued);
  els.catalogProgressPanel.classList.toggle('hidden', !running);
  const globalPercent = Math.max(0, Math.min(100, Number(status?.global_progress_percent || 0)));
  els.catalogGlobalPercent.textContent = `${globalPercent} %`;
  els.catalogGlobalBar.value = globalPercent;
  els.catalogGlobalBar.textContent = `${globalPercent} %`;
  els.catalogGlobalBar.className = `catalog-progress-meter ${globalPercent >= 100 ? 'progress-ok' : 'progress-running'}`;
  els.catalogCurrentSupplier.textContent = running && status?.current_supplier
    ? `Fournisseur en cours : ${status.current_supplier}`
    : (running ? 'Préparation de la prochaine collecte fournisseur…' : '');
  els.catalogSupplierProgress.innerHTML = suppliers.map(supplier => {
    const percent = Math.max(0, Math.min(100, Number(supplier.progress_percent || 0)));
    const labels = {pending: 'En attente', running: 'En cours', ok: 'Prêt', unavailable: 'Indisponible', failed: 'Échec', missing: 'Absent'};
    const label = labels[supplier.status] || supplier.status || 'Inconnu';
    const stateClass = ['ok', 'unavailable', 'failed', 'running', 'pending', 'missing'].includes(supplier.status)
      ? `progress-${supplier.status}`
      : 'progress-missing';
    return `<div class="catalog-supplier-row"><div class="catalog-progress-heading"><span>${escapeHtml(supplier.site_name)}</span><strong>${percent} % · ${escapeHtml(label)}</strong></div><progress class="catalog-progress-meter ${stateClass}" max="100" value="${percent}">${percent} %</progress></div>`;
  }).join('');
}

async function loadCatalogSyncStatus() {
  try {
    const status = await fetchJson('/api/pieces/catalog-sync', {cache: 'no-store'}, 10000);
    renderCatalogSync(status);
    return status;
  } catch (error) {
    state.catalogReady = false;
    state.catalogRunning = false;
    state.catalogStatusLoaded = false;
    els.catalogProgressPanel.classList.add('hidden');
    state.catalogSuppliers = {};
    state.recoveredCatalogCount = 0;
    els.catalogSyncState.textContent = `Catalogues fournisseurs : statut temporairement indisponible (${error.message}).`;
    els.lastSyncDate.textContent = 'Dernière synchronisation : inconnue';
    els.catalogWaitNotice.textContent = 'Le serveur contrôle ou met à jour les catalogues. Patientez : la recherche sera réactivée automatiquement dès que le service répondra.';
    els.catalogWaitNotice.classList.remove('hidden');
    setDisabled(els.selectAllSites, true);
    setDisabled(els.clearAllSites, true);
    if (state.sites.length) renderSites();
    validateForm();
    return null;
  }
}

function startSyncPolling() {
  if (state.syncPoll) return;
  state.syncPoll = window.setInterval(loadCatalogSyncStatus, CATALOG_STATUS_INTERVAL_MS);
}


function selectedValues(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked:not(:disabled)`)].map(input => input.value);
}

function selectedModel() {
  return document.querySelector('input[name="model"]:checked:not(:disabled)')?.value || null;
}

function validateForm() {
  const hasConfiguredSite = state.sitesChecked && state.sites.length > 0;
  const selectedSites = selectedValues('site');
  const recoveredCatalogAvailable = hasAtLeastOneRecoveredCatalog();
  const selectedCatalogsReady = selectedSites.length >= 1 && selectedSites.every(siteId => supplierCatalogUsable(siteId));
  const syncControlsLocked = !recoveredCatalogAvailable || state.catalogRunning;
  const supplierSelectionLocked = !state.catalogReady || state.catalogRunning;
  setDisabled(els.keywords, syncControlsLocked);
  els.keywords.title = state.catalogRunning
    ? 'Saisie désactivée pendant la récupération des catalogues.'
    : (recoveredCatalogAvailable ? '' : 'Saisie désactivée : aucun catalogue valide n’est encore disponible.');
  els.exampleQueries.forEach(button => { button.disabled = syncControlsLocked; });
  setDisabled(els.selectAllSites, supplierSelectionLocked);
  setDisabled(els.clearAllSites, supplierSelectionLocked);
  const valid = state.connectivityOnline
    && !state.sitesLoading
    && hasConfiguredSite
    && Boolean(selectedModel())
    && recoveredCatalogAvailable
    && !state.catalogRunning
    && selectedCatalogsReady
    && !els.keywords.disabled
    && els.keywords.value.trim().length >= 2;
  els.searchButton.disabled = state.loading || !valid;
  if (!state.connectivityOnline) {
    els.searchButton.title = 'Recherche désactivée : connexion Internet indisponible.';
  } else if (state.sitesLoading || !state.sitesChecked) {
    els.searchButton.title = 'Recherche désactivée pendant la vérification des boutiques.';
  } else if (!hasConfiguredSite) {
    els.searchButton.title = 'Recherche désactivée : aucun fournisseur chargé.';
  } else if (state.catalogRunning) {
    els.searchButton.title = 'Recherche désactivée pendant la récupération des catalogues.';
  } else if (!recoveredCatalogAvailable) {
    els.searchButton.title = 'Recherche désactivée : les catalogues ne sont pas récupérés ou ne sont plus à jour.';
  } else if (!selectedCatalogsReady) {
    els.searchButton.title = 'Recherche désactivée : sélectionnez au moins un fournisseur dont le catalogue est prêt.';
  } else {
    els.searchButton.removeAttribute('title');
  }
  return valid;
}


els.keywords.addEventListener('input', validateForm);
document.querySelectorAll('input[name="model"]').forEach(input => input.addEventListener('change', validateForm));

function setAllSites(checked) {
  if (!state.catalogReady || state.catalogRunning) return;
  state.userTouchedSites = true;
  els.sitesGrid.querySelectorAll('input[name="site"]:not(:disabled)').forEach(input => {
    input.checked = checked;
  });
  validateForm();
}

els.selectAllSites.addEventListener('click', () => setAllSites(true));
els.clearAllSites.addEventListener('click', () => setAllSites(false));

els.exampleQueries.forEach(button => {
  button.addEventListener('click', () => {
    if (button.disabled || els.keywords.disabled) return;
    els.keywords.value = button.dataset.query || '';
    validateForm();
    els.keywords.focus();
  });
});

els.searchForm.addEventListener('submit', async event => {
  event.preventDefault();
  els.formError.classList.add('hidden');
  const keywords = els.keywords.value.trim();
  await loadCatalogSyncStatus();
  const model = selectedModel();
  const selectedSites = selectedValues('site');
    if (!model || model !== '1900') return showFormError('Le modèle de véhicule est imposé à GT 1900.');
  if (selectedSites.length < 1) return showFormError('Activez au moins un fournisseur pour lancer la recherche.');
  if (!selectedSitesHaveReadyCatalogs()) return showFormError('Sélectionnez uniquement des fournisseurs dont le catalogue est prêt. Les fournisseurs non récupérables ont été désactivés.');
  if (keywords.length < 2) return showFormError('Saisissez au moins deux caractères pour décrire la pièce.');

  setLoading(true);
  alignResultsPanel();
  try {
    const result = await fetchJson('/api/pieces/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model, keywords, sites: selectedSites}),
    }, 75000);
    state.offers = [...(result.offers || [])];
    state.suggestions = result.suggestions || [];
    state.ambiguityReasons = result.ambiguity_reasons || [];
    state.currentQuery = result.query || keywords;
    state.currentPage = 1;
    renderConnectivity(result.connectivity?.online ?? true, result.connectivity?.detail || '', result.connectivity?.conclusive ?? true);
    renderSearchResult(result);
    alignResultsPanel();
  } catch (error) {
    showFormError(`La recherche n'a pas abouti : ${error.message}`);
    await checkConnectivity(true);
  } finally {
    setLoading(false);
  }
});

function setLoading(loading) {
  state.loading = loading;
  els.progressPanel.classList.toggle('hidden', !loading);
  if (loading) {
    els.resultsContent.classList.add('hidden');
    els.resultsSummary.textContent = 'Recherche en cours…';
  }
  els.searchButton.innerHTML = loading
    ? '<span class="spinner" aria-hidden="true"></span> Recherche en cours…'
    : '<span aria-hidden="true">⌕</span> Comparer les pièces';
  validateForm();
}

function showFormError(message) {
  els.formError.textContent = message;
  els.formError.classList.remove('hidden');
  els.formError.scrollIntoView({behavior: 'smooth', block: 'center'});
}

function savedResultFilters() {
  try {
    const value = JSON.parse(localStorage.getItem(FILTER_STORAGE_KEY) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch { return {}; }
}

function saveResultFilters() {
  localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify({
    supplier: els.supplierFilter.value,
    priceMin: els.priceMin.value,
    priceMax: els.priceMax.value,
    availability: els.availabilityFilter.value,
    sort: els.sortResults.value,
    pageSize: state.pageSize,
  }));
}

function applySavedResultFilters() {
  const saved = savedResultFilters();
  const supplierValues = [...els.supplierFilter.options].map(option => option.value);
  els.supplierFilter.value = supplierValues.includes(saved.supplier) ? saved.supplier : '';
  els.priceMin.value = saved.priceMin || '';
  els.priceMax.value = saved.priceMax || '';
  const availabilityValues = [...els.availabilityFilter.options].map(option => option.value);
  els.availabilityFilter.value = availabilityValues.includes(saved.availability) ? saved.availability : '';
  const sortValues = [...els.sortResults.options].map(option => option.value);
  els.sortResults.value = sortValues.includes(saved.sort) ? saved.sort : 'price_asc';
  const pageSize = Number(saved.pageSize);
  state.pageSize = [25, 50, 100, 200, 500].includes(pageSize) ? pageSize : DEFAULT_PAGE_SIZE;
  els.pageSize.value = String(state.pageSize);
}

function renderSearchResult(result) {
  els.resultsContent.classList.remove('hidden');
  resetResultControls();
  renderSuggestions(result.ambiguous);
  renderPage();
}

function resetResultControls() {
  const suppliers = [...new Set(state.offers.map(offer => offer.site_name).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, 'fr', {sensitivity: 'base'}));
  els.supplierFilter.innerHTML = '<option value="">Tous les fournisseurs</option>' + suppliers.map(name =>
    `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`
  ).join('');
  els.priceMin.setCustomValidity('');
  els.priceMax.setCustomValidity('');
  applySavedResultFilters();
  state.currentPage = 1;
}

function normalizedAvailability(value) {
  return value || 'unknown';
}

function normalizedAvailabilityLabel(offer) {
  return String(offer?.availability_label || '').trim().toLocaleLowerCase('fr-FR');
}

function offerMatchesAvailability(offer, filter) {
  if (!filter) return true;
  const availability = normalizedAvailability(offer.availability);
  const label = normalizedAvailabilityLabel(offer);
  if (filter === 'on_request') return label === 'sur demande';
  if (filter === 'unknown') return availability === 'unknown' && label !== 'sur demande';
  return availability === filter;
}

function priceValue(offer) {
  const value = Number(offer.price);
  return Number.isFinite(value) ? value : null;
}

function confidenceValue(offer) {
  const value = Number(offer.query_confidence);
  return Number.isFinite(value) ? value : 0;
}

function compareText(a, b) {
  return String(a || '').localeCompare(String(b || ''), 'fr', {sensitivity: 'base'});
}

function comparePrices(a, b, descending = false) {
  const left = priceValue(a);
  const right = priceValue(b);
  if (left === null && right === null) return compareText(a.site_name, b.site_name) || compareText(a.title, b.title);
  if (left === null) return 1;
  if (right === null) return -1;
  const difference = descending ? right - left : left - right;
  return difference || compareText(a.site_name, b.site_name) || compareText(a.title, b.title);
}

function filteredAndSortedOffers() {
  const supplier = els.supplierFilter.value;
  const availability = els.availabilityFilter.value;
  const minValue = els.priceMin.value === '' ? null : Number(els.priceMin.value);
  const maxValue = els.priceMax.value === '' ? null : Number(els.priceMax.value);
  const invalidRange = minValue !== null && maxValue !== null && Number.isFinite(minValue) && Number.isFinite(maxValue) && minValue > maxValue;
  els.priceMax.setCustomValidity(invalidRange ? 'Le prix maximum doit être supérieur ou égal au prix minimum.' : '');

  let offers = invalidRange ? [] : state.offers.filter(offer => {
    if (supplier && offer.site_name !== supplier) return false;
    if (!offerMatchesAvailability(offer, availability)) return false;
    const price = priceValue(offer);
    if (minValue !== null && (!Number.isFinite(minValue) || price === null || price < minValue)) return false;
    if (maxValue !== null && (!Number.isFinite(maxValue) || price === null || price > maxValue)) return false;
    return true;
  });

  const sort = els.sortResults.value || 'price_asc';
  offers = [...offers].sort((a, b) => {
    if (sort === 'price_desc') return comparePrices(a, b, true);
    if (sort === 'availability') {
      const ranks = {in_stock: 0, low_stock: 1, restocking: 2, on_request: 3, out_of_stock: 4, unknown: 5};
      const availabilityKey = offer => normalizedAvailabilityLabel(offer) === 'sur demande' ? 'on_request' : normalizedAvailability(offer.availability);
      const difference = (ranks[availabilityKey(a)] ?? 5) - (ranks[availabilityKey(b)] ?? 5);
      return difference || comparePrices(a, b, false);
    }
    if (sort === 'confidence_asc') return confidenceValue(a) - confidenceValue(b) || comparePrices(a, b, false);
    if (sort === 'confidence_desc') return confidenceValue(b) - confidenceValue(a) || comparePrices(a, b, false);
    if (sort === 'supplier') return compareText(a.site_name, b.site_name) || comparePrices(a, b, false);
    return comparePrices(a, b, false);
  });
  return offers;
}

function updateResultsSummary(visibleCount) {
  const total = state.offers.length;
  const visible = Number.isFinite(visibleCount) ? visibleCount : total;
  if (visible === total) {
    els.resultsSummary.textContent = `${total} résultat${total > 1 ? 's' : ''} conservé${total > 1 ? 's' : ''} pour « ${state.currentQuery} »`;
  } else {
    els.resultsSummary.textContent = `${visible} résultat${visible > 1 ? 's' : ''} affiché${visible > 1 ? 's' : ''} sur ${total} pour « ${state.currentQuery} »`;
  }
}

function renderPage() {
  state.visibleOffers = filteredAndSortedOffers();
  const totalPages = Math.max(1, Math.ceil(state.visibleOffers.length / state.pageSize));
  state.currentPage = Math.min(state.currentPage, totalPages);
  const start = (state.currentPage - 1) * state.pageSize;
  const pageOffers = state.visibleOffers.slice(start, start + state.pageSize);
  const hasResults = state.visibleOffers.length > 0;
  const hasUnfilteredResults = state.offers.length > 0;
  els.resultsControls.classList.toggle('hidden', !hasUnfilteredResults);
  els.exportCsvButton.classList.toggle('hidden', !hasUnfilteredResults);
  els.exportCsvButton.disabled = !hasResults;
  els.resultsTableWrap.classList.toggle('hidden', !hasResults);
  els.emptyState.classList.toggle('hidden', hasResults);
  if (!hasResults && hasUnfilteredResults) {
    els.emptyStateTitle.textContent = 'Aucun résultat pour ces filtres';
    els.emptyStateText.textContent = 'Modifiez les filtres ou réinitialisez-les pour afficher les autres résultats.';
  } else if (!hasResults) {
    els.emptyStateTitle.textContent = 'Aucun résultat trouvé';
    els.emptyStateText.textContent = "Essayez une autre formulation ou l'un des mots-clés proposés ci-dessus.";
  }
  els.resultsTableBody.innerHTML = pageOffers.map(renderOfferRow).join('');
  els.resultsTableBody.querySelectorAll('[data-remove-id]').forEach(button => {
    button.addEventListener('click', () => removeOffer(button.dataset.removeId));
  });
  els.resultsTableBody.querySelectorAll('.result-photo img').forEach(image => {
    image.addEventListener('error', () => {
      image.closest('a').innerHTML = '<span class="image-placeholder">Photo indisponible</span>';
    }, {once: true});
  });
  const showPagination = totalPages > 1;
  els.pagination.classList.toggle('hidden', !showPagination);
  els.pageInfo.textContent = `Page ${state.currentPage} sur ${totalPages} · jusqu'à ${state.pageSize} résultats par page`;
  els.prevPage.disabled = state.currentPage <= 1;
  els.nextPage.disabled = state.currentPage >= totalPages;
  els.filterSummary.textContent = hasUnfilteredResults && state.visibleOffers.length !== state.offers.length
    ? `${state.visibleOffers.length} résultat${state.visibleOffers.length > 1 ? 's' : ''} après filtrage sur ${state.offers.length}.`
    : '';
  updateResultsSummary(state.visibleOffers.length);
}

function renderOfferRow(offer) {
  const image = offer.image_url
    ? `<img src="${escapeHtml(safeUrl(offer.image_url))}" alt="Photo de ${escapeHtml(offer.title)}" loading="lazy" referrerpolicy="no-referrer">`
    : '<span class="image-placeholder">Sans photo</span>';
  const price = Number.isFinite(offer.price)
    ? formatMoney(offer.price, offer.currency)
    : (offer.availability_label === 'Sur demande' ? 'Sur demande' : 'Prix inconnu');
  const confidence = Math.round((offer.query_confidence || 0) * 100);
  const availability = availabilityBadge(offer);
  const priceHistory = renderPriceHistory(offer, price);
  return `
    <tr data-offer-id="${escapeHtml(offer.id)}">
      <td class="result-title" data-label="Titre"><a href="${escapeHtml(safeUrl(offer.url))}" target="_blank" rel="noopener noreferrer nofollow">${escapeHtml(offer.title)}</a></td>
      <td class="result-photo" data-label="Photo"><a href="${escapeHtml(safeUrl(offer.url))}" target="_blank" rel="noopener noreferrer nofollow">${image}</a></td>
      <td class="result-supplier" data-label="Fournisseur">${escapeHtml(offer.site_name)}</td>
      <td class="result-price" data-label="Prix">${priceHistory}</td>
      <td class="result-availability" data-label="Disponibilité"><span class="stock-badge ${availability.className}">${availability.label}</span></td>
      <td class="result-confidence" data-label="Confiance"><strong>${confidence} %</strong></td>
      <td class="result-action" data-label="Retirer"><button type="button" class="remove-result" data-remove-id="${escapeHtml(offer.id)}" aria-label="Supprimer ${escapeHtml(offer.title)} des résultats" title="Supprimer cette ligne">×</button></td>
    </tr>`;
}

function renderPriceHistory(offer, formattedPrice) {
  const previous = Number(offer.previous_price);
  const current = Number(offer.price);
  if (!Number.isFinite(previous) || !Number.isFinite(current) || !offer.price_trend) {
    return escapeHtml(formattedPrice);
  }
  const trend = offer.price_trend;
  const symbol = trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→';
  const label = trend === 'up' ? 'Prix en hausse' : trend === 'down' ? 'Prix en baisse' : 'Prix stable';
  const previousText = formatMoney(previous, offer.currency);
  const delta = current - previous;
  const deltaText = formatMoney(Math.abs(delta), offer.currency);
  const dateText = offer.previous_price_date ? ` — observation précédente : ${new Date(offer.previous_price_date).toLocaleString('fr-FR')}` : '';
  const title = `${label} : précédent ${previousText}${trend === 'stable' ? '' : `, écart ${deltaText}`}${dateText}`;
  return `<span class="price-with-trend"><span>${escapeHtml(formattedPrice)}</span><span class="price-trend price-trend-${escapeHtml(trend)}" role="img" aria-label="${escapeHtml(label)}" title="${escapeHtml(title)}">${symbol}</span></span>`;
}

function safeCsvCell(value) {
  let text = value === null || value === undefined ? '' : String(value);
  if (/^[=+@-]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

function exportResultsCsv() {
  const offers = filteredAndSortedOffers();
  if (!offers.length) return;
  const headers = ['Requête', 'Titre', 'Fournisseur', 'Prix', 'Devise', 'Prix précédent', 'Tendance', 'Disponibilité', 'Confiance (%)', 'Référence', 'URL'];
  const rows = offers.map(offer => [
    state.currentQuery,
    offer.title,
    offer.site_name,
    Number.isFinite(Number(offer.price)) ? Number(offer.price).toFixed(2) : '',
    offer.currency || '',
    Number.isFinite(Number(offer.previous_price)) ? Number(offer.previous_price).toFixed(2) : '',
    offer.price_trend === 'up' ? 'hausse' : offer.price_trend === 'down' ? 'baisse' : offer.price_trend === 'stable' ? 'stable' : '',
    offer.availability_label || '',
    Math.round((offer.query_confidence || 0) * 100),
    offer.reference || '',
    offer.url || '',
  ]);
  const csv = '\uFEFF' + [headers, ...rows].map(row => row.map(safeCsvCell).join(';')).join('\r\n');
  const blob = new Blob([csv], {type: 'text/csv;charset=utf-8'});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  const stamp = new Date().toISOString().slice(0, 10);
  link.download = `comparateur-opel-gt-${stamp}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

function availabilityBadge(offer) {
  const value = normalizedAvailability(offer?.availability);
  const sourceLabel = String(offer?.availability_label || '').trim();
  if (sourceLabel.toLocaleLowerCase('fr-FR') === 'sur demande') return {label: 'sur demande', className: 'stock-on-request'};
  if (value === 'in_stock') return {label: 'en stock', className: 'stock-in'};
  if (value === 'low_stock') return {label: 'stock limité', className: 'stock-low'};
  if (value === 'out_of_stock') return {label: 'pas de stock', className: 'stock-out'};
  if (value === 'restocking') return {label: 'réapprovisionnement', className: 'stock-restocking'};
  return {label: sourceLabel || 'à confirmer', className: 'stock-unknown'};
}

function removeOffer(id) {
  state.offers = state.offers.filter(offer => offer.id !== id);
  state.currentPage = 1;
  renderPage();
}

function renderSuggestions(isAmbiguous = false) {
  const hasSuggestions = state.suggestions.length > 0;
  els.suggestionsPanel.classList.toggle('hidden', !hasSuggestions);
  if (!hasSuggestions) {
    els.suggestionList.innerHTML = '';
    return;
  }
  if (!state.offers.length) {
    els.suggestionsReason.textContent = 'Aucun fournisseur n’a renvoyé de correspondance dans le titre. Essayez une formulation voisine :';
  } else if (isAmbiguous || state.ambiguityReasons.length) {
    els.suggestionsReason.textContent = `${state.ambiguityReasons.join(' ')} Vous pouvez préciser la recherche :`;
  } else {
    els.suggestionsReason.textContent = 'Essayez une formulation voisine :';
  }
  els.suggestionList.innerHTML = state.suggestions.map(suggestion =>
    `<button type="button" class="suggestion-button" data-suggestion="${escapeHtml(suggestion)}">${escapeHtml(suggestion)}</button>`
  ).join('');
  els.suggestionList.querySelectorAll('button').forEach(button => {
    button.addEventListener('click', () => {
      if (els.keywords.disabled) return;
      els.keywords.value = button.dataset.suggestion || '';
      validateForm();
      els.keywords.focus();
      document.querySelector('#searchTitle')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    });
  });
}

function formatMoney(value, currency) {
  try { return new Intl.NumberFormat('fr-FR', {style: 'currency', currency: currency || 'EUR', maximumFractionDigits: 2}).format(value); }
  catch { return `${Number(value).toFixed(2)} ${currency || ''}`.trim(); }
}

[els.supplierFilter, els.availabilityFilter, els.sortResults].forEach(control => {
  control.addEventListener('change', () => {
    state.currentPage = 1;
    saveResultFilters();
    renderPage();
  });
});
els.pageSize.addEventListener('change', () => {
  const value = Number(els.pageSize.value);
  state.pageSize = [25, 50, 100, 200, 500].includes(value) ? value : DEFAULT_PAGE_SIZE;
  state.currentPage = 1;
  saveResultFilters();
  renderPage();
});
[els.priceMin, els.priceMax].forEach(control => {
  control.addEventListener('input', () => {
    state.currentPage = 1;
    saveResultFilters();
    renderPage();
  });
});
els.resetResultFilters.addEventListener('click', () => {
  localStorage.removeItem(FILTER_STORAGE_KEY);
  resetResultControls();
  renderPage();
});
els.exportCsvButton.addEventListener('click', exportResultsCsv);

els.prevPage.addEventListener('click', () => {
  if (state.currentPage > 1) {
    state.currentPage -= 1;
    renderPage();
    els.resultsPanel.scrollIntoView({behavior: 'smooth'});
  }
});
els.nextPage.addEventListener('click', () => {
  const totalPages = Math.max(1, Math.ceil(state.visibleOffers.length / state.pageSize));
  if (state.currentPage < totalPages) {
    state.currentPage += 1;
    renderPage();
    els.resultsPanel.scrollIntoView({behavior: 'smooth'});
  }
});

window.addEventListener('offline', () => { checkConnectivity(true); });
window.addEventListener('online', async () => { await loadSites(true); await loadCatalogSyncStatus(); });

els.logoutButton.addEventListener('click', logout);

bootstrapAuthentication();


