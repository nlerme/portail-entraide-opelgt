'use strict';

const $ = id => document.getElementById(id);
const state = {csrf: '', editor: null, logs: [], tab: 'config', ntfy: null, metrics: [], metricsTimer: null, metricsHoverIndex: null, metricsRefreshMs: Number(localStorage.getItem('opelgt-admin-metrics-refresh')) || 2000};

class ApiError extends Error {
  constructor(message, payload = {}, status = 0) {
    super(message);
    this.payload = payload;
    this.status = status;
  }
}

async function api(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const headers = {'Content-Type': 'application/json', ...(options.headers || {})};
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && state.csrf) headers['X-CSRF-Token'] = state.csrf;
  const response = await fetch(path, {credentials: 'same-origin', ...options, headers});
  let payload = {};
  try { payload = await response.json(); } catch {}
  if (response.status === 401) {
    showLogin('La session administrateur a expiré.');
    throw new ApiError(payload.message || 'Session administrateur expirée.', payload, response.status);
  }
  if (!response.ok || payload.ok === false) {
    throw new ApiError(payload.message || payload.detail || `HTTP ${response.status}`, payload, response.status);
  }
  return payload;
}

const esc = value => String(value ?? '—').replace(/[&<>'"]/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
}[character]));

function show(id, visible) {
  $(id).classList.toggle('hidden', !visible);
}

function normalizedPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(100, number)) : null;
}

function formatPercent(value) {
  const percent = normalizedPercent(value);
  if (percent === null) return '';
  return `${percent.toLocaleString('fr-FR', {maximumFractionDigits: 1})} %`;
}

function positiveTone(value) {
  const percent = normalizedPercent(value) ?? 0;
  if (percent >= 90) return 'green';
  if (percent >= 60) return 'orange';
  return 'red';
}

function inverseTone(value, warningThreshold = 1, dangerThreshold = 5) {
  const percent = normalizedPercent(value) ?? 0;
  if (percent >= dangerThreshold) return 'red';
  if (percent >= warningThreshold) return 'orange';
  return 'green';
}

function metric(label, value, tone = 'neutral', percent = null) {
  const formattedPercent = formatPercent(percent);
  const percentage = formattedPercent ? `<span class="metric-percent">${esc(formattedPercent)}</span>` : '';
  return `<article class="status-card status-card-${tone}"><h3>${esc(label)}</h3><div class="status-value-line"><strong>${esc(value)}</strong>${percentage}</div></article>`;
}

function formatDuration(minutes) {
  const value = Math.max(1, Number(minutes) || 30);
  return `${value} minute${value > 1 ? 's' : ''}`;
}

function applySession(session) {
  state.csrf = session.csrfToken || '';
  $('adminSessionDuration').textContent = formatDuration(session.durationMinutes);
  window.SessionTimer.start({
    expiresAt: session.expiresAt,
    serverTime: session.serverTime,
    durationMinutes: session.durationMinutes,
    element: $('sessionRemaining'),
    onExpire: () => window.SessionLifecycle.expire(),
  });
  window.SessionLifecycle.start({sessionKind: 'admin', token: state.csrf});
}

function showLogin(message = '') {
  state.csrf = '';
  state.ntfy = null;
  $('ntfyToken').value = '';
  $('ntfyPassword').value = '';
  $('ntfyFields').disabled = true;
  window.SessionTimer.stop();
  window.SessionLifecycle.stop();
  stopMetricsPolling();
  show('header', false);
  show('app', false);
  $('loginMessage').textContent = message;
  $('loginMessage').className = message ? 'message error' : 'message hidden';
  if (!$('loginDialog').open) $('loginDialog').showModal();
}

function enter(session) {
  applySession(session);
  if ($('loginDialog').open) $('loginDialog').close();
  show('header', true);
  show('app', true);
  refreshAll();
  startMetricsPolling();
}

async function init() {
  window.PortalUI.startConnectivity();
  state.editor = new window.CodeEditorLite($('configEditor'), {language: 'json', label: 'Configuration JSON'});
  bind();
  try {
    const session = await api('/api/admin/session');
    $('adminSessionDuration').textContent = formatDuration(session.durationMinutes);
    if (session.authenticated) enter(session);
    else showLogin();
  } catch {
    showLogin();
  }
}

function bind() {
  $('loginForm').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const session = await api('/api/admin/login', {
        method: 'POST',
        body: JSON.stringify({username: $('username').value, password: $('password').value}),
      });
      $('password').value = '';
      enter(session);
    } catch (error) {
      $('password').value = '';
      $('loginMessage').textContent = error.message;
      $('loginMessage').className = 'message error';
    }
  });
  $('logout').addEventListener('click', async () => {
    window.SessionTimer.stop();
    window.SessionLifecycle.stop();
    stopMetricsPolling();
    try { await api('/api/admin/logout', {method: 'POST'}); } catch {}
    window.location.reload();
  });
  $('reloadConfig').addEventListener('click', loadConfig);
  $('saveConfig').addEventListener('click', saveConfig);
  $('refreshLogs').addEventListener('click', loadLogs);
  $('ntfyForm').addEventListener('submit', saveNtfy);
  $('reloadNtfy').addEventListener('click', loadNtfy);
  $('ntfyEnabled').addEventListener('change', updateNtfyFields);
  $('ntfyAuth').addEventListener('change', () => {
    $('ntfyToken').value = '';
    $('ntfyPassword').value = '';
    updateNtfyFields();
  });
  document.querySelectorAll('.admin-tab').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.tab)));
  document.querySelectorAll('[data-control]').forEach(button => button.addEventListener('click', () => control(button.dataset.control, button)));
  $('metricsRefreshInterval').value = String(state.metricsRefreshMs);
  $('metricsRefreshInterval').addEventListener('change', event => {
    state.metricsRefreshMs = Math.max(1000, Number(event.target.value) || 2000);
    localStorage.setItem('opelgt-admin-metrics-refresh', String(state.metricsRefreshMs));
    if (state.csrf) startMetricsPolling();
  });
  $('systemMetricsChart').addEventListener('pointermove', handleMetricsPointerMove);
  $('systemMetricsChart').addEventListener('pointerleave', () => { state.metricsHoverIndex = null; $('systemMetricsTooltip').classList.add('hidden'); drawMetricsChart(); });
  window.addEventListener('resize', drawMetricsChart);
  window.addEventListener('portal-theme-changed', drawMetricsChart);
}

function switchTab(tab) {
  state.tab = tab;
  document.querySelectorAll('.admin-tab').forEach(button => button.classList.toggle('active', button.dataset.tab === tab));
  document.querySelectorAll('.admin-tab-panel').forEach(panel => panel.classList.toggle('active', panel.id === `tab-${tab}`));
  refreshDynamic();
}

async function refreshAll() {
  await Promise.allSettled([loadConfig(), loadNtfy(), loadStatus(), loadStats(), loadLogs(), loadJobs()]);
}

async function refreshDynamic() {
  if (state.tab === 'ntfy' && !state.ntfy) await loadNtfy();
  if (state.tab === 'status') await Promise.all([loadStatus(), loadMetrics()]);
  if (state.tab === 'stats') await loadStats();
  if (state.tab === 'logs') await loadLogs();
  if (state.tab === 'jobs') await loadJobs();
}

async function loadConfig() {
  const payload = await api('/api/admin/config');
  $('configPath').textContent = `Fichier : ${payload.path}`;
  state.editor.setValue(payload.content);
}

async function saveConfig() {
  const message = $('configMessage');
  try {
    const payload = await api('/api/admin/config', {method: 'PUT', body: JSON.stringify({content: state.editor.getValue()})});
    message.textContent = payload.message;
    message.className = 'message success';
  } catch (error) {
    message.textContent = error.message;
    message.className = 'message error';
  }
}

function updateNtfyFields() {
  const enabled = $('ntfyEnabled').checked;
  const mode = $('ntfyAuth').value;
  const sameMode = state.ntfy && state.ntfy.auth === mode;
  const hasToken = sameMode && state.ntfy.has_token;
  const hasPassword = sameMode && state.ntfy.has_password;
  for (const id of ['ntfyServer', 'ntfyTopic', 'ntfyAuth']) $(id).disabled = !enabled;
  $('ntfyServer').required = enabled;
  $('ntfyTopic').required = enabled;
  for (const [row, id, visible, stored] of [
    ['ntfyUsernameRow', 'ntfyUsername', mode === 'basic', false],
    ['ntfyTokenRow', 'ntfyToken', mode === 'token', hasToken],
    ['ntfyPasswordRow', 'ntfyPassword', mode === 'basic', hasPassword],
  ]) {
    show(row, enabled && visible);
    $(id).disabled = !enabled || !visible;
    $(id).required = enabled && visible && !stored;
  }
  $('ntfyTokenHint').textContent = hasToken ? 'Un jeton est enregistré. Laissez vide pour le conserver.' : 'Saisissez un jeton autorisé à publier dans ce sujet.';
  $('ntfyPasswordHint').textContent = hasPassword ? 'Un mot de passe est enregistré. Laissez vide pour le conserver.' : 'Saisissez le mot de passe du compte ntfy.';
}

function applyNtfySettings(settings) {
  state.ntfy = settings;
  $('ntfyEnabled').checked = settings.enabled;
  $('ntfyServer').value = settings.server || 'https://ntfy.sh';
  $('ntfyTopic').value = settings.topic || '';
  $('ntfyAuth').value = settings.auth || 'none';
  $('ntfyUsername').value = settings.username || '';
  $('ntfyInterval').value = String(settings.interval_days || 1);
  $('ntfyToken').value = '';
  $('ntfyPassword').value = '';
  $('ntfyFields').disabled = false;
  updateNtfyFields();
}

async function loadNtfy() {
  const message = $('ntfyMessage');
  try {
    applyNtfySettings(await api('/api/admin/ntfy'));
    message.className = 'message hidden';
  } catch (error) {
    $('ntfyToken').value = '';
    $('ntfyPassword').value = '';
    message.textContent = error.message;
    message.className = 'message error';
  }
}

async function saveNtfy(event) {
  event.preventDefault();
  const message = $('ntfyMessage');
  const enabled = $('ntfyEnabled').checked;
  const settings = {enabled, interval_days: Number($('ntfyInterval').value)};
  if (enabled) {
    Object.assign(settings, {server: $('ntfyServer').value.trim(), topic: $('ntfyTopic').value.trim(), auth: $('ntfyAuth').value});
    if (settings.auth === 'basic') {
      settings.username = $('ntfyUsername').value.trim();
      if ($('ntfyPassword').value) settings.password = $('ntfyPassword').value;
    }
    if (settings.auth === 'token' && $('ntfyToken').value) settings.token = $('ntfyToken').value;
  }
  $('saveNtfy').disabled = true;
  try {
    const payload = await api('/api/admin/ntfy', {method: 'PUT', body: JSON.stringify(settings)});
    applyNtfySettings(payload.settings);
    message.textContent = payload.message;
    message.className = 'message success';
  } catch (error) {
    message.textContent = error.message;
    message.className = 'message error';
  } finally {
    $('ntfyToken').value = '';
    $('ntfyPassword').value = '';
    $('saveNtfy').disabled = false;
  }
}

async function control(action, button) {
  const output = $('controlOutput');
  output.textContent = 'Action en cours…';
  button.disabled = true;
  try {
    const payload = await api('/api/admin/control', {method: 'POST', body: JSON.stringify({action})});
    output.textContent = payload.message || JSON.stringify(payload, null, 2);
    output.className = 'admin-output is-success';
  } catch (error) {
    output.textContent = error.message + (error.payload.terminalCommand ? `\nCommande terminal : ${error.payload.terminalCommand}` : '');
    output.className = 'admin-output is-error';
  } finally {
    button.disabled = false;
  }
}

async function loadStatus() {
  const payload = await api('/api/admin/status');
  const bulletins = payload.services.bulletins || {};
  const pieces = payload.services.pieces || {};
  const storage = payload.storage || {};
  $('generalStatus').innerHTML = [
    metric('Version', payload.version, 'blue'),
    metric('Synchronisation bulletins', bulletins.message || bulletins.phase, 'blue'),
    metric('Catalogues', pieces.detail || '—', 'blue'),
    metric('Tâches actives', payload.jobs.active, 'blue'),
    metric('Espace libre', formatBytes(storage.freeBytes), 'blue'),
    metric('Répertoire de données', storage.dataRoot, 'blue'),
  ].join('');
}

function stopMetricsPolling() {
  if (state.metricsTimer !== null) window.clearInterval(state.metricsTimer);
  state.metricsTimer = null;
}

function startMetricsPolling() {
  stopMetricsPolling();
  loadMetrics();
  state.metricsTimer = window.setInterval(loadMetrics, state.metricsRefreshMs);
}

function cpuColor(index) {
  const colors = ['#0072b2', '#009e73', '#cc79a7', '#e69f00', '#56b4e9', '#d55e00', '#332288', '#88ccee'];
  return colors[index % colors.length];
}

async function loadMetrics() {
  if (!state.csrf) return;
  try {
    const payload = await api('/api/admin/metrics');
    const cpus = Array.isArray(payload.cpuPercents)
      ? payload.cpuPercents.map(value => Math.max(0, Math.min(100, Number(value) || 0)))
      : [Math.max(0, Math.min(100, Number(payload.cpuPercent) || 0))];
    const cpuLabels = Array.isArray(payload.cpuLabels) && payload.cpuLabels.length === cpus.length
      ? payload.cpuLabels.map(String)
      : cpus.map((_value, index) => `CPU ${index + 1}`);
    state.metrics.push({
      timestamp: Number(payload.timestamp) || Date.now() / 1000,
      cpus,
      cpuLabels,
      ram: Math.max(0, Math.min(100, Number(payload.memoryPercent) || 0)),
      memoryUsedBytes: Number(payload.memoryUsedBytes) || 0,
      memoryTotalBytes: Number(payload.memoryTotalBytes) || 0,
    });
    if (state.metrics.length > 90) state.metrics.splice(0, state.metrics.length - 90);
    const latest = state.metrics[state.metrics.length - 1];
    const cpuLegend = latest.cpus.map((value, index) => `<span class="metric-legend"><i class="metric-cpu-color-${index % 8}"></i>${esc(latest.cpuLabels[index])} : <strong>${value.toLocaleString('fr-FR', {maximumFractionDigits: 1})} %</strong></span>`).join('');
    $('systemMetricsLegend').innerHTML = `${cpuLegend}<span class="metric-legend metric-ram"><i></i>RAM : <strong>${latest.ram.toLocaleString('fr-FR', {maximumFractionDigits: 1})} %</strong> (${formatBytes(latest.memoryUsedBytes)} / ${formatBytes(latest.memoryTotalBytes)})</span>`;
    const cpuAria = latest.cpus.map((value, index) => `${latest.cpuLabels[index]} ${value.toFixed(1)} %`).join(', ');
    $('systemMetricsChart').setAttribute('aria-label', `${cpuAria}, mémoire vive ${latest.ram.toFixed(1)} %`);
    drawMetricsChart();
  } catch (error) {
    if (error.status !== 401) console.warn('Mesures système indisponibles.', error);
  }
}

function chartPalette() {
  const dark = document.documentElement.dataset.theme === 'dark';
  return {
    grid: dark ? 'rgba(203,213,225,.20)' : 'rgba(71,85,105,.18)',
    text: dark ? '#cbd5e1' : '#475569',
    background: dark ? '#172130' : '#ffffff',
    ram: '#d55e00',
    focus: dark ? '#f8fafc' : '#111827',
  };
}

function drawMetricsChart() {
  const canvas = $('systemMetricsChart');
  const wrap = $('systemMetricsChartWrap');
  if (!canvas || !wrap) return;
  const width = Math.max(320, wrap.clientWidth || 0);
  const height = 280;
  const ratio = Math.max(1, window.devicePixelRatio || 1);
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const palette = chartPalette();
  ctx.fillStyle = palette.background;
  ctx.fillRect(0, 0, width, height);
  const bounds = {left: 46, right: 14, top: 16, bottom: 32};
  const plotWidth = width - bounds.left - bounds.right;
  const plotHeight = height - bounds.top - bounds.bottom;
  ctx.font = '12px system-ui, sans-serif';
  ctx.lineWidth = 1;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let value = 0; value <= 100; value += 25) {
    const y = bounds.top + plotHeight * (1 - value / 100);
    ctx.strokeStyle = palette.grid;
    ctx.beginPath(); ctx.moveTo(bounds.left, y); ctx.lineTo(width - bounds.right, y); ctx.stroke();
    ctx.fillStyle = palette.text;
    ctx.fillText(`${value} %`, bounds.left - 7, y);
  }
  if (state.metrics.length < 2) {
    ctx.textAlign = 'center';
    ctx.fillStyle = palette.text;
    ctx.fillText('Collecte des mesures en cours…', bounds.left + plotWidth / 2, bounds.top + plotHeight / 2);
    return;
  }
  const pointX = index => bounds.left + plotWidth * index / Math.max(1, state.metrics.length - 1);
  const pointY = value => bounds.top + plotHeight * (1 - value / 100);
  const drawSeries = (valueAt, color) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.2;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.beginPath();
    state.metrics.forEach((point, index) => {
      const value = valueAt(point);
      if (!Number.isFinite(value)) return;
      const x = pointX(index); const y = pointY(value);
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  };
  const cpuCount = Math.max(...state.metrics.map(point => point.cpus.length), 0);
  for (let cpuIndex = 0; cpuIndex < cpuCount; cpuIndex += 1) {
    drawSeries(point => point.cpus[cpuIndex], cpuColor(cpuIndex));
  }
  drawSeries(point => point.ram, palette.ram);
  const first = new Date(state.metrics[0].timestamp * 1000);
  const last = new Date(state.metrics[state.metrics.length - 1].timestamp * 1000);
  ctx.fillStyle = palette.text;
  ctx.textBaseline = 'top';
  ctx.textAlign = 'left';
  ctx.fillText(first.toLocaleTimeString('fr-FR'), bounds.left, height - bounds.bottom + 8);
  ctx.textAlign = 'right';
  ctx.fillText(last.toLocaleTimeString('fr-FR'), width - bounds.right, height - bounds.bottom + 8);
  if (Number.isInteger(state.metricsHoverIndex) && state.metrics[state.metricsHoverIndex]) {
    const index = state.metricsHoverIndex;
    const point = state.metrics[index];
    const x = pointX(index);
    ctx.strokeStyle = palette.focus;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(x, bounds.top); ctx.lineTo(x, bounds.top + plotHeight); ctx.stroke();
    ctx.setLineDash([]);
    point.cpus.forEach((value, cpuIndex) => {
      ctx.fillStyle = cpuColor(cpuIndex);
      ctx.beginPath(); ctx.arc(x, pointY(value), 4, 0, Math.PI * 2); ctx.fill();
    });
    ctx.fillStyle = palette.ram;
    ctx.beginPath(); ctx.arc(x, pointY(point.ram), 4, 0, Math.PI * 2); ctx.fill();
  }
}

function handleMetricsPointerMove(event) {
  if (!state.metrics.length) return;
  const canvas = $('systemMetricsChart');
  const rect = canvas.getBoundingClientRect();
  const left = 46;
  const right = 14;
  const plotWidth = Math.max(1, rect.width - left - right);
  const relative = Math.max(0, Math.min(1, (event.clientX - rect.left - left) / plotWidth));
  state.metricsHoverIndex = Math.round(relative * Math.max(0, state.metrics.length - 1));
  const point = state.metrics[state.metricsHoverIndex];
  const tooltip = $('systemMetricsTooltip');
  const cpuRows = point.cpus.map((value, index) => `<span>${esc(point.cpuLabels[index] || `CPU ${index + 1}`)} : ${value.toFixed(1)} %</span>`).join('');
  tooltip.innerHTML = `<strong>${new Date(point.timestamp * 1000).toLocaleTimeString('fr-FR')}</strong>${cpuRows}<span>RAM : ${point.ram.toFixed(1)} %</span>`;
  tooltip.classList.remove('hidden');
  const x = left + plotWidth * state.metricsHoverIndex / Math.max(1, state.metrics.length - 1);
  tooltip.style.left = `${Math.max(8, Math.min(rect.width - 190, x + 12))}px`;
  tooltip.style.top = '18px';
  drawMetricsChart();
}

function areaLabel(value) {
  return value === 'admin' ? 'Administration' : 'Compte membre';
}

function outcomeLabel(value) {
  return ({success: 'Réussie', failed: 'Identifiants refusés', 'rate-limited': 'Bloquée par la limite', error: 'Erreur du site membre', 'https-required': 'HTTPS requis'})[value] || value || 'Inconnu';
}

function countryFlag(countryCode) {
  const code = String(countryCode || '').trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(code)) return '';
  return [...code].map(character => String.fromCodePoint(0x1F1E6 + character.charCodeAt(0) - 65)).join('');
}

function countryLabel(row, includeCode = true) {
  const flag = countryFlag(row.country_code);
  const country = esc(row.country || 'Inconnu');
  const code = includeCode && row.country_code ? ` (${esc(row.country_code)})` : '';
  return `${flag ? `${flag} ` : ''}${country}${code}`;
}

async function loadStats() {
  const payload = await api('/api/admin/statistics');
  const bulletinTotal = Number(payload.bulletins.total) || 0;
  const bulletinIndexed = Number(payload.bulletins.indexed) || 0;
  const bulletinFailed = Number(payload.bulletins.failed) || 0;
  const indexCoverage = bulletinTotal ? normalizedPercent(payload.bulletins.coveragePercent) : null;
  const bulletinFailureRate = bulletinTotal ? bulletinFailed / bulletinTotal * 100 : null;
  const supplierTotal = Number(payload.pieces.suppliers) || 0;
  const supplierAvailable = Number(payload.pieces.available) || 0;
  const supplierAvailability = supplierTotal ? supplierAvailable / supplierTotal * 100 : null;
  const connectionTotal = Number(payload.connections.summary.total) || 0;
  const connectionSuccess = Number(payload.connections.summary.successful) || 0;
  const connectionBlocked = Number(payload.connections.summary.blocked) || 0;
  const connectionSuccessRate = connectionTotal ? connectionSuccess / connectionTotal * 100 : null;
  const connectionBlockedRate = connectionTotal ? connectionBlocked / connectionTotal * 100 : null;

  $('statistics').innerHTML = [
    metric('Bulletins téléchargés', bulletinTotal, 'neutral'),
    metric('Bulletins indexés', bulletinIndexed, indexCoverage === null ? 'neutral' : positiveTone(indexCoverage), indexCoverage),
    metric('Pages indexées', payload.bulletins.pages, 'neutral'),
    metric('Erreurs bulletins', bulletinFailed, bulletinFailureRate === null ? 'neutral' : inverseTone(bulletinFailureRate, 0.1, 2), bulletinFailureRate),
    metric('Couverture de l’index', `${bulletinIndexed}/${bulletinTotal}`, indexCoverage === null ? 'neutral' : positiveTone(indexCoverage), indexCoverage),
    metric('Catalogues disponibles', `${supplierAvailable}/${supplierTotal}`, supplierAvailability === null ? 'neutral' : positiveTone(supplierAvailability), supplierAvailability),
    metric('Pièces cataloguées', payload.pieces.items, 'neutral'),
    metric('Tâches actives', payload.jobs.active, 'neutral'),
    metric('Tentatives de connexion', connectionTotal, 'neutral'),
    metric('Adresses IP distinctes', payload.connections.summary.unique_ips || 0, 'neutral'),
    metric('Connexions réussies', connectionSuccess, connectionSuccessRate === null ? 'neutral' : positiveTone(connectionSuccessRate), connectionSuccessRate),
    metric('Tentatives bloquées', connectionBlocked, connectionBlockedRate === null ? 'neutral' : inverseTone(connectionBlockedRate, 0.1, 5), connectionBlockedRate),
  ].join('');
  const byIp = (payload.connections.byIp || []).map(row => `<tr><td>${esc(areaLabel(row.area))}</td><td><code>${esc(row.ip_address)}</code></td><td>${countryLabel(row)}</td><td>${esc(row.attempts)}</td><td>${esc(row.successful)}</td><td>${esc(row.failed)}</td><td>${esc(row.blocked)}</td><td>${esc(row.last_attempt)}</td></tr>`).join('');
  const recent = (payload.connections.recent || []).map(row => `<tr><td>${esc(row.created_at)}</td><td>${esc(areaLabel(row.area))}</td><td><code>${esc(row.ip_address)}</code></td><td>${countryLabel(row)}</td><td>${esc(outcomeLabel(row.outcome))}</td></tr>`).join('');
  $('connectionStatistics').innerHTML = `<h3>Connexions par adresse IP</h3><div class="table-wrap"><table><thead><tr><th>Accès</th><th>Adresse IP</th><th>Pays</th><th>Tentatives</th><th>Réussies</th><th>Refusées</th><th>Bloquées</th><th>Dernière tentative</th></tr></thead><tbody>${byIp || '<tr><td colspan="8">Aucune tentative enregistrée.</td></tr>'}</tbody></table></div><h3>Dernières tentatives</h3><div class="table-wrap"><table><thead><tr><th>Date</th><th>Accès</th><th>Adresse IP</th><th>Pays</th><th>Résultat</th></tr></thead><tbody>${recent || '<tr><td colspan="5">Aucune tentative enregistrée.</td></tr>'}</tbody></table></div>`;
}

function jobTone(value) {
  const stateName = String(value || '').toLowerCase();
  if (/(done|success|succeeded|complete|completed|ok|termin)/.test(stateName)) return 'success';
  if (/(fail|error|cancel|dead|échec)/.test(stateName)) return 'error';
  if (/(run|active|working|progress|cours)/.test(stateName)) return 'running';
  return 'pending';
}

async function loadJobs() {
  const payload = await api('/api/jobs?limit=100');
  const rows = payload.jobs.map(job => {
    const tone = jobTone(job.state);
    return `<tr class="job-row job-row-${tone}"><td>${esc(job.queue)}</td><td>${esc(job.job_type)}</td><td><span class="job-state-badge job-state-${tone}">${esc(job.state)}</span></td><td><span class="job-progress-badge">${esc(job.progress_percent)} %</span></td><td>${esc(job.message)}</td><td>${esc(job.created_at)}</td></tr>`;
  }).join('');
  $('jobsTable').innerHTML = `<div class="table-wrap jobs-table-wrap"><table class="jobs-table"><thead><tr><th>File</th><th>Type</th><th>État</th><th>Progression</th><th>Message</th><th>Créée</th></tr></thead><tbody>${rows || '<tr><td colspan="6">Aucune tâche.</td></tr>'}</tbody></table></div>`;
}

async function loadLogs() {
  const payload = await api('/api/admin/logs');
  const container = $('logsContainer');
  container.replaceChildren();
  state.logs = [];
  payload.logs.forEach(entry => {
    const article = document.createElement('article');
    article.className = 'log-block';
    const heading = document.createElement('h3');
    heading.textContent = entry.source;
    const host = document.createElement('div');
    host.className = 'code-editor code-log-viewer';
    article.append(heading, host);
    container.append(article);
    state.logs.push(new window.CodeEditorLite(host, {language: 'log', readOnly: true, label: `Log ${entry.source}`, value: entry.content}));
  });
}

function formatBytes(value) {
  let size = Number(value || 0);
  const units = ['o', 'Kio', 'Mio', 'Gio', 'Tio'];
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toLocaleString('fr-FR', {maximumFractionDigits: 1})} ${units[index]}`;
}

document.addEventListener('DOMContentLoaded', init);
