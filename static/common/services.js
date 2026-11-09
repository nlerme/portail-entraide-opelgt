'use strict';

let csrfToken = '';
let refreshTimer = null;
let refreshEnabled = true;

async function requestJson(url, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const headers = {...(options.headers || {})};
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken;
  const response = await fetch(url, {...options, method, headers, cache: 'no-store', credentials: 'include'});
  let payload = {};
  try { payload = await response.json(); } catch {}
  if (response.status === 401) {
    refreshEnabled = false;
    window.SessionLifecycle.stop();
    window.location.replace('/');
    throw new Error('Session expirée.');
  }
  if (!response.ok) throw new Error(payload.message || `Erreur HTTP ${response.status}`);
  return payload;
}

function setStatus(selector, ok, text) {
  const element = document.querySelector(selector);
  element.textContent = text;
  element.className = `status ${ok ? 'ok' : 'warn'}`;
}

function setProgress(barSelector, labelSelector, value, state = 'running') {
  const percent = Math.max(0, Math.min(100, Number(value) || 0));
  const bar = document.querySelector(barSelector);
  bar.value = percent;
  bar.textContent = `${percent} %`;
  bar.className = `progress-meter progress-${state}`;
  document.querySelector(labelSelector).textContent = `${percent} %`;
}

function setServiceLink(selector, enabled) {
  const link = document.querySelector(selector);
  link.classList.toggle('disabled', !enabled);
  link.setAttribute('aria-disabled', String(!enabled));
  link.tabIndex = enabled ? 0 : -1;
}

function renderBulletins(status) {
  const processing = Boolean(status.running);
  const label = processing ? 'Préparation en cours' : (status.ready ? 'Recherche disponible' : 'Service accessible');
  setStatus('#bulletinsStatus', !processing, label);
  document.querySelector('#bulletinsDetail').textContent = `${status.localPdfCount || 0} PDF téléchargé(s), ${status.indexedBulletins || 0} bulletin(s) et ${status.indexedPages || 0} page(s) indexée(s).`;
  document.querySelector('#bulletinsFrequency').textContent = status.automaticFrequency || '';
  document.querySelector('#bulletinsProgress').classList.toggle('hidden', !processing);
  const downloadPercent = Math.max(0, Math.min(100, Number(status.downloadProgressPercent) || 0));
  const indexPercent = Math.max(0, Math.min(100, Number(status.indexProgressPercent) || 0));
  const downloadState = status.downloadRunning ? 'running' : (downloadPercent >= 100 ? 'ok' : 'pending');
  const indexState = status.indexingRunning ? (indexPercent >= 100 ? 'ok' : 'running') : (indexPercent >= 100 ? 'ok' : 'pending');
  setProgress('#bulletinsDownloadBar', '#bulletinsDownloadPercent', downloadPercent, downloadState);
  setProgress('#bulletinsIndexBar', '#bulletinsIndexPercent', indexPercent, indexState);
  const current = status.current ? `Fichier en cours : ${status.current}` : (status.message || 'Traitement en cours.');
  document.querySelector('#bulletinsCurrent').textContent = processing ? current : '';
  setServiceLink('#bulletinsOpen', Boolean(status.available));
}

function supplierLabel(supplier) {
  const labels = {pending: 'En attente', running: 'En cours', ok: 'Prêt', unavailable: 'Indisponible', failed: 'Échec', missing: 'Absent'};
  return labels[supplier.status] || supplier.status || 'Inconnu';
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>'"]/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[character]));
}

function renderPieces(status) {
  const processing = Boolean(status.running);
  const label = processing ? 'Catalogues en préparation' : (status.ready ? 'Comparateur disponible' : 'Service accessible');
  setStatus('#piecesStatus', !processing, label);
  document.querySelector('#piecesDetail').textContent = `${status.availableCatalogs || 0} catalogue(s) fournisseur(s) disponible(s). ${status.message || ''}`.trim();
  document.querySelector('#piecesFrequency').textContent = status.automaticFrequency || '';
  document.querySelector('#piecesProgress').classList.toggle('hidden', !processing);
  const globalPercent = Math.max(0, Math.min(100, Number(status.globalProgressPercent) || 0));
  setProgress('#piecesGlobalBar', '#piecesGlobalPercent', globalPercent, globalPercent >= 100 ? 'ok' : 'running');
  document.querySelector('#piecesCurrent').textContent = processing && status.currentSupplier ? `Fournisseur en cours : ${status.currentSupplier}` : '';
  document.querySelector('#piecesSuppliers').innerHTML = (status.suppliers || []).map(supplier => {
    const percent = Math.max(0, Math.min(100, Number(supplier.progress_percent) || 0));
    const stateClass = ['ok', 'unavailable', 'failed', 'running', 'pending', 'missing'].includes(supplier.status)
      ? `progress-${supplier.status}`
      : 'progress-missing';
    return `<div class="supplier-progress"><div class="progress-label"><span>${escapeHtml(supplier.site_name)}</span><strong>${percent} % · ${escapeHtml(supplierLabel(supplier))}</strong></div><progress class="progress-meter ${stateClass}" max="100" value="${percent}">${percent} %</progress></div>`;
  }).join('');
  setServiceLink('#piecesOpen', Boolean(status.available));
}

function renderAnnonces(status) {
  if (!document.querySelector('#annoncesStatus')) return;
  const running = !status || Boolean(status.running);
  setStatus('#annoncesStatus', Boolean(status), status ? (running ? 'Actualisation en cours · accès disponible' : 'Petites annonces disponibles') : 'État indisponible');
  document.querySelector('#annoncesDetail').textContent = running
    ? `${status?.count || 0} annonce(s) consultable(s) pendant la collecte.`
    : `${status.count || 0} annonce(s) d’Opel GT d’époque en France. ${(status.sources || []).filter(source => source.status !== 'ok').map(source => `${source.name} : ${source.message}`).join(' ')}`;
  document.querySelector('#annoncesFrequency').textContent = status?.automaticFrequency || 'Mise à jour automatique tous les jours à 02:00 (Europe/Paris).';
  setServiceLink('#annoncesOpen', Boolean(status));
  const direct = document.querySelector('#leboncoinDirect');
  const leboncoin = status?.sources?.find(source => source.id === 'leboncoin');
  direct?.classList.toggle('hidden', !leboncoin || leboncoin.status === 'ok');
}

async function refreshServices() {
  try {
    const status = await requestJson('/api/services');
    renderBulletins(status.bulletins);
    renderPieces(status.pieces);
    renderAnnonces(status.annonces);
  } catch (error) {
    if (error.message === 'Session expirée.') return;
    setStatus('#bulletinsStatus', false, error.message);
    setStatus('#piecesStatus', false, error.message);
    renderAnnonces(null);
  } finally {
    if (refreshEnabled) refreshTimer = window.setTimeout(refreshServices, 2000);
  }
}

async function initialize() {
  const session = await requestJson('/api/session');
  if (!session.authenticated) {
    refreshEnabled = false;
    window.SessionLifecycle.stop();
    window.location.replace('/');
    return;
  }
  csrfToken = session.csrfToken || '';
  window.SessionTimer.start({
    expiresAt: session.expiresAt,
    serverTime: session.serverTime,
    durationMinutes: session.durationMinutes,
    element: document.querySelector('#sessionRemaining'),
    onExpire: () => window.SessionLifecycle.expire(),
  });
  window.SessionLifecycle.start({sessionKind: 'member', token: csrfToken});
  window.PortalUI.startConnectivity();
  await refreshServices();
}

document.querySelectorAll('.service-card .button').forEach(link => link.addEventListener('click', event => {
  if (link.getAttribute('aria-disabled') === 'true') event.preventDefault();
}));

document.querySelector('#logout').addEventListener('click', async () => {
  refreshEnabled = false;
  if (refreshTimer) window.clearTimeout(refreshTimer);
  window.SessionTimer.stop();
  window.SessionLifecycle.stop();
  window.PortalUI.stopConnectivity();
  try { await requestJson('/api/logout', {method: 'POST'}); } catch {}
  window.location.replace('/');
});

initialize().catch(error => {
  setStatus('#bulletinsStatus', false, error.message);
  setStatus('#piecesStatus', false, error.message);
  renderAnnonces(null);
});
