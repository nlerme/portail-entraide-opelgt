'use strict';

const state = {
  payload: null,
  rows: [],
  csrfToken: '',
  selectedViewId: '',
  selectedRowId: null,
  selectedReference: '',
  splitPercent: 38,
  partsCollapsed: false,
  workspaceHeight: null,
};

const els = {
  html: document.documentElement,
  appShell: document.querySelector('#appShell'),
  sessionRemaining: document.querySelector('#sessionRemaining'),
  logoutButton: document.querySelector('#logoutButton'),
  themeButton: document.querySelector('#themeButton'),
  themeIcon: document.querySelector('#themeIcon'),
  themeLabel: document.querySelector('#themeLabel'),
  fontDecrease: document.querySelector('#fontDecrease'),
  fontIncrease: document.querySelector('#fontIncrease'),
  resultSummary: document.querySelector('#resultSummary'),
  searchInput: document.querySelector('#searchInput'),
  sectionFilter: document.querySelector('#sectionFilter'),
  viewFilter: document.querySelector('#viewFilter'),
  resetFilters: document.querySelector('#resetFilters'),
  message: document.querySelector('#message'),
  partsList: document.querySelector('#partsList'),
  emptyState: document.querySelector('#emptyState'),
  sourceNote: document.querySelector('#sourceNote'),
  viewSelect: document.querySelector('#viewSelect'),
  viewPdfLink: document.querySelector('#viewPdfLink'),
  selectedPartDetail: document.querySelector('#selectedPartDetail'),
  diagramImageWrap: document.querySelector('#diagramImageWrap'),
  diagramImage: document.querySelector('#diagramImage'),
  diagramMarkers: document.querySelector('#diagramMarkers'),
  markerMatches: document.querySelector('#markerMatches'),
  categoryLegend: document.querySelector('#categoryLegend'),
  referenceWorkspace: document.querySelector('#referenceWorkspace'),
  partsPane: document.querySelector('#partsPane'),
  workspaceSplitter: document.querySelector('#workspaceSplitter'),
  togglePartsPane: document.querySelector('#togglePartsPane'),
  workspaceHeightHandle: document.querySelector('#workspaceHeightHandle'),
  splitterToggleIcon: document.querySelector('#splitterToggleIcon'),
};

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, character => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'}[character]));
}

function normalize(value = '') {
  return String(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
}

function canonicalReference(value = '') {
  const text = String(value || '').trim();
  const match = text.match(/\d+\s*\+?/);
  return match ? match[0].replace(/\s+/g, '') : text;
}

function splitReferences(value) {
  const text = String(value || '').trim();
  if (!text) return [];
  return text.split(/\s*,\s*/).filter(Boolean).map(label => ({
    label,
    reference: canonicalReference(label),
    uncertain: /pas certain|confirmer/i.test(label),
  }));
}

function formatTorque(value) {
  return Number(value).toLocaleString('fr-FR', {minimumFractionDigits:1, maximumFractionDigits:1});
}

const MARKER_RADIUS = 27;
const MARKER_HIT_RADIUS = 45;
const MARKER_SELECTED_RADIUS = 37.5;
const MARKER_UNCERTAIN_RADIUS = 36;

const SECTION_CLASS_NAMES = {
  'Moteur': 'section-engine',
  'Direction': 'section-steering',
  'Suspension avant': 'section-front-suspension',
  'Suspension arrière': 'section-rear-suspension',
  'Freins': 'section-brakes',
};

function sectionClass(section) {
  return SECTION_CLASS_NAMES[section] || 'section-default';
}

function sectionsForReference(viewId, reference) {
  return [...new Set(rowsForReference(viewId, reference).map(row => row.section))];
}

async function fetchJson(url, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const headers = {...(options.headers || {})};
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && state.csrfToken) headers['X-CSRF-Token'] = state.csrfToken;
  const response = await fetch(url, {...options, method, headers, cache:'no-store', credentials:'include'});
  let payload = {};
  try { payload = await response.json(); } catch {}
  if (response.status === 401) {
    window.location.replace('/');
    throw new Error('Session expirée.');
  }
  if (!response.ok) throw new Error(payload.message || `Erreur HTTP ${response.status}`);
  return payload;
}

const SPLIT_STORAGE_KEY = 'opelgt-couples-split';
const SPLIT_MIN = 22;
const SPLIT_MAX = 62;
const STACKED_LAYOUT = matchMedia('(max-width: 900px)');

function clampSplitPercent(value) {
  const numeric = Number(value);
  return Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, Number.isFinite(numeric) ? Math.round(numeric) : 38));
}

function saveSplitState() {
  localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify({percent:state.splitPercent, collapsed:state.partsCollapsed, height:state.workspaceHeight}));
}

function applySplitPercent(value, {persist = true} = {}) {
  const next = clampSplitPercent(value);
  els.referenceWorkspace.classList.remove(`split-${state.splitPercent}`);
  state.splitPercent = next;
  els.referenceWorkspace.classList.add(`split-${next}`);
  els.workspaceSplitter.setAttribute('aria-valuenow', String(next));
  if (persist) saveSplitState();
}

function setPartsPaneCollapsed(collapsed, {persist = true} = {}) {
  state.partsCollapsed = Boolean(collapsed);
  els.referenceWorkspace.classList.toggle('is-parts-collapsed', state.partsCollapsed);
  els.partsPane.setAttribute('aria-hidden', String(state.partsCollapsed));
  els.togglePartsPane.setAttribute('aria-expanded', String(!state.partsCollapsed));
  const label = state.partsCollapsed ? 'Afficher le bloc Pièces et couples' : 'Masquer le bloc Pièces et couples';
  els.togglePartsPane.setAttribute('aria-label', label);
  els.togglePartsPane.title = label;
  els.splitterToggleIcon.textContent = state.partsCollapsed ? '›' : '‹';
  if (persist) saveSplitState();
  requestAnimationFrame(() => {
    const view = viewById(state.selectedViewId);
    if (view) renderMarkers(view);
    if (!state.partsCollapsed) focusSelectedPart();
    centerSelectedMarker();
  });
}

function loadSplitState() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(SPLIT_STORAGE_KEY) || '{}'); } catch {}
  applySplitPercent(saved.percent, {persist:false});
  setPartsPaneCollapsed(Boolean(saved.collapsed), {persist:false});
  if (typeof saved.height === 'number' && Number.isFinite(saved.height)) applyWorkspaceHeight(saved.height, {persist:false});
  updateSplitterOrientation();
}

const HEIGHT_MIN = 480;
const HEIGHT_MAX = 1800;
let heightDrag = null;

function syncHeightHandle() {
  const height = document.querySelector('#viewPane').getBoundingClientRect().height;
  if (height > 0) {
    els.workspaceHeightHandle.setAttribute('aria-valuenow', String(Math.round(height)));
    els.workspaceHeightHandle.setAttribute('aria-valuetext', `${Math.round(height)} pixels par bloc`);
  }
}

function applyWorkspaceHeight(value, {persist = true} = {}) {
  const height = Math.max(HEIGHT_MIN, Math.min(HEIGHT_MAX, Math.round(value)));
  state.workspaceHeight = height;
  els.referenceWorkspace.style.setProperty('--workspace-height', `${height}px`);
  syncHeightHandle();
  if (persist) saveSplitState();
}

function updateSplitterOrientation() {
  const stacked = STACKED_LAYOUT.matches;
  els.workspaceSplitter.setAttribute('aria-orientation', stacked ? 'horizontal' : 'vertical');
  els.workspaceSplitter.dataset.orientation = stacked ? 'stacked' : 'side-by-side';
}

function resizeFromPointer(clientX) {
  if (STACKED_LAYOUT.matches || state.partsCollapsed) return;
  const rect = els.referenceWorkspace.getBoundingClientRect();
  if (!rect.width) return;
  applySplitPercent(((clientX - rect.left) / rect.width) * 100);
}

function viewById(viewId) {
  return state.payload?.views?.find(view => String(view.id) === String(viewId));
}

function rowById(rowId) {
  return state.rows.find(row => Number(row.id) === Number(rowId));
}

function rowMappings(row) {
  return (state.payload?.views || []).flatMap(view => {
    const references = splitReferences(row.views?.[String(view.id)]);
    return references.length ? [{view, references}] : [];
  });
}

function referencesForRowInView(row, viewId) {
  return splitReferences(row?.views?.[String(viewId)]);
}

function rowsForReference(viewId, reference) {
  const wanted = canonicalReference(reference);
  return state.rows.filter(row => {
    if (row.torque_mkg === null || row.torque_mkg === undefined || row.torque_mkg === '') return false;
    return referencesForRowInView(row, viewId).some(entry => entry.reference === wanted);
  });
}

function mappingIsUncertain(view, reference) {
  const wanted = canonicalReference(reference);
  const markerUncertain = (view?.markers || []).some(marker => canonicalReference(marker.reference) === wanted && marker.uncertain);
  const rowUncertain = rowsForReference(view?.id, wanted).some(row => referencesForRowInView(row, view.id).some(entry => entry.reference === wanted && entry.uncertain));
  return markerUncertain || rowUncertain;
}

function filteredRows() {
  const query = normalize(els.searchInput.value);
  const section = els.sectionFilter.value;
  const view = els.viewFilter.value;
  return state.rows.filter(row => {
    if (section && row.section !== section) return false;
    const hasAnyView = rowMappings(row).length > 0;
    if (view === 'none' && hasAnyView) return false;
    if (view && view !== 'none' && !referencesForRowInView(row, view).length) return false;
    if (query && !normalize(`${row.id} ${row.section} ${row.item} ${row.torque_mkg}`).includes(query)) return false;
    return true;
  });
}

function mappingChipMarkup(row, mapping) {
  const refs = mapping.references.map(entry => entry.reference).join(', ');
  const uncertain = mapping.references.some(entry => entry.uncertain);
  const selected = Number(state.selectedRowId) === Number(row.id) && String(state.selectedViewId) === String(mapping.view.id);
  const title = `Afficher ${mapping.view.label}, repère${mapping.references.length > 1 ? 's' : ''} ${refs}`;
  return `<button type="button" class="part-view-chip${selected ? ' is-active' : ''}${uncertain ? ' is-uncertain' : ''}" data-row-id="${row.id}" data-view-id="${escapeHtml(mapping.view.id)}" title="${escapeHtml(title)}">${escapeHtml(mapping.view.label)} · repère${mapping.references.length > 1 ? 's' : ''} ${escapeHtml(refs)}${uncertain ? ' ?' : ''}</button>`;
}

function renderPartsList({focusSelected = false} = {}) {
  const rows = filteredRows();
  els.partsList.innerHTML = rows.map(row => {
    const selected = Number(state.selectedRowId) === Number(row.id);
    const mappings = rowMappings(row);
    const views = mappings.length
      ? mappings.map(mapping => mappingChipMarkup(row, mapping)).join('')
      : '<span class="part-no-view">Aucune vue éclatée disponible</span>';
    return `<article id="part-row-${row.id}" class="part-card ${sectionClass(row.section)}${selected ? ' is-selected' : ''}" role="option" aria-selected="${selected}" data-row-id="${row.id}">
      <button type="button" class="part-select-button" data-row-id="${row.id}">
        <span class="part-meta"><b>L${row.id}</b><span>${escapeHtml(row.section)}</span></span>
        <span class="part-title">${escapeHtml(row.item)}</span>
        <span class="part-torque">${formatTorque(row.torque_mkg)} ${escapeHtml(state.payload.unit)}</span>
      </button>
      <div class="part-views" aria-label="Vues disponibles pour ${escapeHtml(row.item)}">${views}</div>
    </article>`;
  }).join('');
  els.emptyState.classList.toggle('hidden', rows.length !== 0);
  els.resultSummary.textContent = `${rows.length} / ${state.rows.length} pièce${rows.length > 1 ? 's' : ''}`;
  if (focusSelected) window.requestAnimationFrame(focusSelectedPart);
}

function markerTitle(view, reference) {
  const rows = rowsForReference(view.id, reference);
  const details = rows.map(row => `L${row.id} : ${row.item}, ${formatTorque(row.torque_mkg)} ${state.payload.unit}`).join(' ; ');
  const uncertain = mappingIsUncertain(view, reference) ? ' Correspondance à confirmer.' : '';
  return `Repère ${canonicalReference(reference)}. ${details}.${uncertain}`;
}

function markerSegmentsMarkup(sections) {
  const safeSections = sections.length ? sections : [''];
  const count = safeSections.length;
  const gap = count > 1 ? 3 : 0;
  const segment = (100 / count) - gap;
  return safeSections.map((section, index) => {
    const dashOffset = -(index * (100 / count) + gap / 2);
    return `<circle class="marker-segment ${sectionClass(section)}" r="${MARKER_RADIUS}" pathLength="100" stroke-dasharray="${segment.toFixed(3)} ${(100 - segment).toFixed(3)}" stroke-dashoffset="${dashOffset.toFixed(3)}"></circle>`;
  }).join('');
}

function markerMarkup(view, marker, markerIndex, imageWidth, imageHeight) {
  const reference = canonicalReference(marker.reference);
  const sourceWidth = Number(view.image_width || imageWidth);
  const sourceHeight = Number(view.image_height || imageHeight);
  const xPercent = Math.max(0, Math.min(100, Number(marker.x_percent) || 0));
  const yPercent = Math.max(0, Math.min(100, Number(marker.y_percent) || 0));
  const sourceX = Number.isFinite(Number(marker.x_px)) ? Number(marker.x_px) : sourceWidth * xPercent / 100;
  const sourceY = Number.isFinite(Number(marker.y_px)) ? Number(marker.y_px) : sourceHeight * yPercent / 100;
  const x = imageWidth * sourceX / sourceWidth;
  const y = imageHeight * sourceY / sourceHeight;
  const selectedRow = rowById(state.selectedRowId);
  const selectedReferences = referencesForRowInView(selectedRow, view.id).map(entry => entry.reference);
  const selected = selectedReferences.includes(reference);
  const uncertain = Boolean(marker.uncertain) || mappingIsUncertain(view, reference);
  const sections = sectionsForReference(view.id, reference);
  const classes = ['mapping-marker', selected ? 'is-selected' : '', uncertain ? 'is-uncertain' : ''].filter(Boolean).join(' ');
  const title = markerTitle(view, reference);
  return `<g class="${classes}" transform="translate(${x.toFixed(3)} ${y.toFixed(3)})" data-view-id="${escapeHtml(view.id)}" data-reference="${escapeHtml(reference)}" data-marker-index="${markerIndex}" data-x="${x.toFixed(3)}" data-y="${y.toFixed(3)}" role="button" tabindex="0" aria-label="${escapeHtml(title)}">
    <title>${escapeHtml(title)}</title>
    <circle class="marker-hit-area" r="${MARKER_HIT_RADIUS}"></circle>
    <circle class="marker-halo" r="${MARKER_RADIUS}"></circle>
    ${markerSegmentsMarkup(sections)}
    <circle class="marker-selected-ring" r="${MARKER_SELECTED_RADIUS}"></circle>
    <circle class="marker-uncertain-ring" r="${MARKER_UNCERTAIN_RADIUS}"></circle>
  </g>`;
}

function renderMarkers(view) {
  const width = Number(els.diagramImage.naturalWidth || 0);
  const height = Number(els.diagramImage.naturalHeight || 0);
  if (!width || !height || els.diagramImage.dataset.viewId !== String(view.id)) {
    els.diagramMarkers.replaceChildren();
    return;
  }
  els.diagramMarkers.setAttribute('viewBox', `0 0 ${width} ${height}`);
  els.diagramMarkers.setAttribute('aria-label', `${view.label} : repères interactifs des pièces disposant d’un couple de serrage`);
  els.diagramMarkers.innerHTML = (view.markers || [])
    .filter(marker => rowsForReference(view.id, marker.reference).length)
    .map((marker, index) => markerMarkup(view, marker, index, width, height))
    .join('');
  window.requestAnimationFrame(centerSelectedMarker);
}

function renderView() {
  const view = viewById(state.selectedViewId);
  if (!view) return;
  els.viewSelect.value = String(view.id);
  els.viewPdfLink.href = view.pdf;
  els.diagramImage.alt = `${view.label} avec repères interactifs des pièces disposant d’un couple de serrage`;
  els.diagramImage.dataset.viewId = String(view.id);
  if (els.diagramImage.getAttribute('src') === view.image && els.diagramImage.complete) {
    renderMarkers(view);
  } else {
    els.diagramMarkers.replaceChildren();
    els.diagramImage.src = view.image;
  }
  renderSelectedPartDetail();
}

function renderSelectedPartDetail() {
  const row = rowById(state.selectedRowId);
  const view = viewById(state.selectedViewId);
  if (!row || !view) {
    els.selectedPartDetail.innerHTML = '<p>Sélectionnez une pièce dans la liste de gauche.</p>';
    return;
  }
  const mappings = rowMappings(row);
  const currentRefs = referencesForRowInView(row, view.id);
  const allViews = mappings.length
    ? mappings.map(mapping => `${mapping.view.label} : ${mapping.references.map(entry => `repère ${entry.reference}`).join(', ')}`).join(' · ')
    : 'Aucune vue éclatée disponible';
  const currentMessage = currentRefs.length
    ? `<span class="selected-location">Localisation actuelle : ${escapeHtml(view.label)}, repère${currentRefs.length > 1 ? 's' : ''} ${escapeHtml(currentRefs.map(entry => entry.reference).join(', '))}</span>`
    : `<span class="selected-location is-unavailable">Cette pièce n’est pas repérée dans ${escapeHtml(view.label)}.</span>`;
  els.selectedPartDetail.innerHTML = `<div class="selected-part-heading">
      <span class="selected-line">L${row.id}</span>
      <div><p>${escapeHtml(row.section)}</p><h3>${escapeHtml(row.item)}</h3></div>
      <strong>${formatTorque(row.torque_mkg)} ${escapeHtml(state.payload.unit)}</strong>
    </div>
    <div class="selected-part-locations">${currentMessage}<span>Vues disponibles : ${escapeHtml(allViews)}</span></div>`;
}

function renderMarkerMatches(reference = '') {
  const view = viewById(state.selectedViewId);
  const rows = reference && view ? rowsForReference(view.id, reference) : [];
  if (rows.length <= 1) {
    els.markerMatches.classList.add('hidden');
    els.markerMatches.innerHTML = '';
    return;
  }
  els.markerMatches.innerHTML = `<strong>Le repère ${escapeHtml(reference)} correspond à plusieurs lignes :</strong><div>${rows.map(row => `<button type="button" class="marker-match-button${Number(row.id) === Number(state.selectedRowId) ? ' is-active' : ''}" data-row-id="${row.id}">L${row.id} · ${escapeHtml(row.item)} · ${formatTorque(row.torque_mkg)} ${escapeHtml(state.payload.unit)}</button>`).join('')}</div>`;
  els.markerMatches.classList.remove('hidden');
}

function focusSelectedPart() {
  const selected = document.querySelector(`#part-row-${Number(state.selectedRowId)}`);
  if (!selected) return;
  const containerRect = els.partsList.getBoundingClientRect();
  const selectedRect = selected.getBoundingClientRect();
  if (selectedRect.top < containerRect.top || selectedRect.bottom > containerRect.bottom) {
    const target = els.partsList.scrollTop + selectedRect.top - containerRect.top - (containerRect.height - selectedRect.height) / 2;
    els.partsList.scrollTo({top: Math.max(0, target), behavior:'auto'});
  }
  selected.querySelector('.part-select-button')?.focus({preventScroll:true});
}

function centerSelectedMarker() {
  const marker = els.diagramMarkers.querySelector('.mapping-marker.is-selected');
  if (!marker) return;
  const markerRect = marker.getBoundingClientRect();
  const wrapRect = els.diagramImageWrap.getBoundingClientRect();
  const markerCenterX = els.diagramImageWrap.scrollLeft + markerRect.left - wrapRect.left + markerRect.width / 2;
  const markerCenterY = els.diagramImageWrap.scrollTop + markerRect.top - wrapRect.top + markerRect.height / 2;
  els.diagramImageWrap.scrollTo({
    left: Math.max(0, markerCenterX - els.diagramImageWrap.clientWidth / 2),
    top: Math.max(0, markerCenterY - els.diagramImageWrap.clientHeight / 2),
    behavior: 'smooth',
  });
}

function selectPart(rowId, preferredViewId = '', {focusSelected = true, preserveReference = false} = {}) {
  const row = rowById(rowId);
  if (!row) return;
  state.selectedRowId = Number(row.id);
  const mappings = rowMappings(row);
  const mappedViewIds = mappings.map(mapping => String(mapping.view.id));
  if (preferredViewId && mappedViewIds.includes(String(preferredViewId))) {
    state.selectedViewId = String(preferredViewId);
  } else if (!mappedViewIds.includes(String(state.selectedViewId)) && mappings.length) {
    state.selectedViewId = String(mappings[0].view.id);
  } else if (!state.selectedViewId && state.payload.views.length) {
    state.selectedViewId = String(state.payload.views[0].id);
  }
  const refs = referencesForRowInView(row, state.selectedViewId);
  if (!preserveReference || !refs.some(entry => entry.reference === state.selectedReference)) {
    state.selectedReference = refs[0]?.reference || '';
  }
  renderPartsList({focusSelected});
  renderView();
  renderMarkerMatches(state.selectedReference);
}

function selectMarker(reference) {
  const view = viewById(state.selectedViewId);
  if (!view) return;
  const canonical = canonicalReference(reference);
  const rows = rowsForReference(view.id, canonical);
  if (!rows.length) return;
  const current = rows.find(row => Number(row.id) === Number(state.selectedRowId));
  const target = current || rows[0];
  if (!filteredRows().some(row => Number(row.id) === Number(target.id))) clearFilters();
  state.selectedReference = canonical;
  selectPart(target.id, view.id, {focusSelected:true, preserveReference:true});
  renderMarkerMatches(canonical);
}

function clearFilters() {
  els.searchInput.value = '';
  els.sectionFilter.value = '';
  els.viewFilter.value = '';
}

function populateSections() {
  els.sectionFilter.insertAdjacentHTML('beforeend', state.payload.sections.map(section => `<option value="${escapeHtml(section)}">${escapeHtml(section)}</option>`).join(''));
}

function renderCategoryLegend() {
  const represented = state.payload.sections.filter(section => state.rows.some(row => row.section === section && rowMappings(row).length));
  els.categoryLegend.innerHTML = represented.map(section => `<span><i class="legend-ring legend-category ${sectionClass(section)}" aria-hidden="true"></i>${escapeHtml(section)}</span>`).join('');
}

function populateViews() {
  const noneOption = els.viewFilter.querySelector('option[value="none"]');
  for (const view of state.payload.views) {
    const filterOption = document.createElement('option');
    filterOption.value = String(view.id);
    filterOption.textContent = `Présentes dans ${view.label.toLowerCase()}`;
    els.viewFilter.insertBefore(filterOption, noneOption);

    const viewOption = document.createElement('option');
    viewOption.value = String(view.id);
    viewOption.textContent = view.label;
    els.viewSelect.appendChild(viewOption);
  }
}

async function initialize() {
  loadSplitState();
  const session = await fetchJson('/api/session');
  if (!session.authenticated) {
    window.location.replace('/');
    return;
  }
  state.csrfToken = session.csrfToken || '';
  window.SessionTimer.start({
    expiresAt: session.expiresAt,
    serverTime: session.serverTime,
    durationMinutes: session.durationMinutes,
    element: els.sessionRemaining,
    onExpire: () => window.SessionLifecycle.expire(),
  });
  window.SessionLifecycle.start({sessionKind: 'member', token: state.csrfToken});
  window.PortalUI.startConnectivity();
  state.payload = await fetchJson('/api/couples');
  state.rows = Array.isArray(state.payload.rows) ? state.payload.rows : [];
  els.sourceNote.textContent = state.payload.source_note || '';
  populateSections();
  populateViews();
  renderCategoryLegend();
  state.selectedViewId = String(state.payload.views[0]?.id || '');
  const firstMappedRow = state.rows.find(row => referencesForRowInView(row, state.selectedViewId).length) || state.rows[0];
  state.selectedRowId = firstMappedRow ? Number(firstMappedRow.id) : null;
  state.selectedReference = referencesForRowInView(firstMappedRow, state.selectedViewId)[0]?.reference || '';
  renderPartsList();
  renderView();
  renderMarkerMatches(state.selectedReference);
  els.appShell.classList.remove('hidden');
}

els.logoutButton.addEventListener('click', async () => {
  window.SessionTimer.stop();
  window.SessionLifecycle.stop();
  window.PortalUI.stopConnectivity();
  try { await fetchJson('/api/logout', {method:'POST'}); } catch {}
  window.location.replace('/');
});
els.searchInput.addEventListener('input', () => renderPartsList());
els.sectionFilter.addEventListener('change', () => renderPartsList());
els.viewFilter.addEventListener('change', () => renderPartsList());
els.resetFilters.addEventListener('click', () => {
  clearFilters();
  renderPartsList();
  els.searchInput.focus();
});
els.partsList.addEventListener('click', event => {
  const viewChip = event.target.closest('.part-view-chip');
  if (viewChip) {
    selectPart(viewChip.dataset.rowId, viewChip.dataset.viewId);
    return;
  }
  const partButton = event.target.closest('.part-select-button');
  if (partButton) selectPart(partButton.dataset.rowId);
});
els.viewSelect.addEventListener('change', () => {
  state.selectedViewId = els.viewSelect.value;
  const selectedRow = rowById(state.selectedRowId);
  state.selectedReference = referencesForRowInView(selectedRow, state.selectedViewId)[0]?.reference || '';
  renderPartsList();
  renderView();
  renderMarkerMatches(state.selectedReference);
});
els.diagramMarkers.addEventListener('click', event => {
  const marker = event.target.closest('.mapping-marker');
  if (marker) selectMarker(marker.dataset.reference || '');
});
els.diagramMarkers.addEventListener('keydown', event => {
  if (!['Enter', ' '].includes(event.key)) return;
  const marker = event.target.closest('.mapping-marker');
  if (!marker) return;
  event.preventDefault();
  selectMarker(marker.dataset.reference || '');
});
els.markerMatches.addEventListener('click', event => {
  const button = event.target.closest('.marker-match-button');
  if (button) selectPart(button.dataset.rowId, state.selectedViewId, {preserveReference:true});
});
els.diagramImage.addEventListener('load', () => {
  const view = viewById(els.diagramImage.dataset.viewId);
  if (view) renderMarkers(view);
});
els.togglePartsPane.addEventListener('click', event => {
  event.stopPropagation();
  setPartsPaneCollapsed(!state.partsCollapsed);
});
els.workspaceSplitter.addEventListener('pointerdown', event => {
  if (event.target.closest('.splitter-toggle') || STACKED_LAYOUT.matches || state.partsCollapsed) return;
  event.preventDefault();
  els.workspaceSplitter.classList.add('is-dragging');
  els.workspaceSplitter.setPointerCapture(event.pointerId);
  resizeFromPointer(event.clientX);
});
els.workspaceSplitter.addEventListener('pointermove', event => {
  if (!els.workspaceSplitter.hasPointerCapture(event.pointerId)) return;
  resizeFromPointer(event.clientX);
});
els.workspaceSplitter.addEventListener('pointerup', event => {
  if (els.workspaceSplitter.hasPointerCapture(event.pointerId)) els.workspaceSplitter.releasePointerCapture(event.pointerId);
  els.workspaceSplitter.classList.remove('is-dragging');
});
els.workspaceSplitter.addEventListener('pointercancel', event => {
  if (els.workspaceSplitter.hasPointerCapture(event.pointerId)) els.workspaceSplitter.releasePointerCapture(event.pointerId);
  els.workspaceSplitter.classList.remove('is-dragging');
});
els.workspaceSplitter.addEventListener('keydown', event => {
  if (STACKED_LAYOUT.matches || state.partsCollapsed) return;
  let next = state.splitPercent;
  if (event.key === 'ArrowLeft') next -= event.shiftKey ? 5 : 1;
  else if (event.key === 'ArrowRight') next += event.shiftKey ? 5 : 1;
  else if (event.key === 'Home') next = SPLIT_MIN;
  else if (event.key === 'End') next = SPLIT_MAX;
  else return;
  event.preventDefault();
  applySplitPercent(next);
});
STACKED_LAYOUT.addEventListener('change', updateSplitterOrientation);

els.workspaceHeightHandle.addEventListener('pointerdown', event => {
  if (event.button !== 0) return;
  event.preventDefault();
  heightDrag = {y:event.clientY, height:document.querySelector('#viewPane').getBoundingClientRect().height,
    factor:STACKED_LAYOUT.matches && !state.partsCollapsed ? 2 : 1};
  els.workspaceHeightHandle.setPointerCapture(event.pointerId);
  els.workspaceHeightHandle.classList.add('is-dragging');
});
els.workspaceHeightHandle.addEventListener('pointermove', event => {
  if (!heightDrag || !els.workspaceHeightHandle.hasPointerCapture(event.pointerId)) return;
  applyWorkspaceHeight(heightDrag.height + (event.clientY - heightDrag.y) / heightDrag.factor, {persist:false});
});
function endHeightDrag(event) {
  if (heightDrag) saveSplitState();
  heightDrag = null;
  if (els.workspaceHeightHandle.hasPointerCapture(event.pointerId)) els.workspaceHeightHandle.releasePointerCapture(event.pointerId);
  els.workspaceHeightHandle.classList.remove('is-dragging');
}
els.workspaceHeightHandle.addEventListener('pointerup', endHeightDrag);
els.workspaceHeightHandle.addEventListener('pointercancel', endHeightDrag);
els.workspaceHeightHandle.addEventListener('lostpointercapture', () => {
  heightDrag = null;
  els.workspaceHeightHandle.classList.remove('is-dragging');
});
els.workspaceHeightHandle.addEventListener('keydown', event => {
  const current = document.querySelector('#viewPane').getBoundingClientRect().height;
  const step = event.shiftKey ? 100 : 20;
  const values = {ArrowUp:current-step, ArrowDown:current+step, PageUp:current-100, PageDown:current+100, Home:HEIGHT_MIN, End:HEIGHT_MAX};
  if (!(event.key in values)) return;
  event.preventDefault();
  applyWorkspaceHeight(values[event.key]);
});
new ResizeObserver(syncHeightHandle).observe(document.querySelector('#viewPane'));

initialize().catch(error => {
  els.message.textContent = error.message;
  els.message.classList.remove('hidden');
  els.appShell.classList.remove('hidden');
});
