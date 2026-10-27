const I18N = {
    "languageName": "Français",
    "loginBrand": "",
    "loginTitle": "Connexion membre",
    "loginIntro": "Identifiez-vous avec votre compte membre. Les identifiants ne sont pas stockés : ils servent uniquement à ouvrir une session locale et à récupérer les PDF accessibles.",
    "loginLabel": "Identifiant",
    "passwordLabel": "Mot de passe",
    "loginButton": "Se connecter",
    "pdfTitle": "Consultation du PDF local",
    "newTab": "Nouvel onglet",
    "close": "Fermer",
    "headerBrand": "",
    "mainTitle": "Recherches dans les bulletins",
    "headerTagline": "Recherche locale dans les bulletins PDF de l’Entraide Opel GT.",
    "languageLabel": "Langue",
    "logout": "Se déconnecter",
    "syncWaiting": "En attente de vérification…",
    "lastSyncUnknown": "Dernière synchronisation : inconnue",
    "lastSyncLabel": "Dernière synchronisation : {value}",
    "searchBlocked": "Les bulletins sont en cours de récupération ou d’indexation. Vous pouvez fermer le navigateur : le traitement continue sur le serveur.",
    "syncEta": "Temps restant estimé : {time}",
    "syncEtaUnknown": "Temps restant : calcul en cours…",
    "searchTitle": "Recherche avancée (sans IA)",
    "keywordsLabel": "Mots clés",
    "keywordsPlaceholder": "Ex. carburateur, joint de pare-brise, frein* OR embrayage*",
    "modeLabel": "Mode",
    "modeAll": "Tous les mots",
    "modeAny": "Au moins un mot",
    "modePhrase": "Expression exacte",
    "modeRaw": "Requête avancée FTS5",
    "limitLabel": "Résultats",
    "yearFromLabel": "Année min.",
    "yearToLabel": "Année max.",
    "bulletinFromLabel": "Bulletin min.",
    "bulletinToLabel": "Bulletin max.",
    "searchButton": "Rechercher",
    "clearButton": "Effacer",
    "helpSummary": "Exemples de requêtes avancées",
    "helpIntro": "Le mode « Requête avancée FTS5 » accepte la syntaxe de l’index SQLite FTS5. Les autres modes construisent la requête automatiquement.",
    "helpAll": "Trouve les pages contenant les deux mots. Utilisez ce type de recherche quand les deux termes sont obligatoires.",
    "helpPhrase": "Recherche les mots dans cet ordre exact, utile pour un nom de pièce ou une expression précise.",
    "helpPrefix": "L’astérisque cherche toutes les variantes qui commencent par ce préfixe : frein, freins, freinage…",
    "helpBool": "OR accepte l’un ou l’autre terme. AND impose les deux. Les parenthèses peuvent regrouper des conditions.",
    "helpNear": "Recherche deux mots proches l’un de l’autre, ici à moins de huit termes.",
    "helpNote": "Astuce : commencez en mode « Tous les mots », puis passez en FTS5 avancé pour les préfixes, OR, AND et NEAR.",
    "resultsTitle": "Résultats",
    "bulletinsTitle": "Liste des bulletins",
    "noBulletinsYet": "Aucun bulletin chargé pour le moment.",
    "tableNo": "N°",
    "tableTitle": "Titre",
    "tableYear": "Année",
    "tablePages": "Pages",
    "tableStatus": "État",
    "tablePdf": "PDF local",
    "footerCopyright": "© 2026 — Entraide Opel GT · Recherche locale des bulletins",
    "footerBuiltWith": "",
    "themeDark": "🌙 Mode sombre",
    "themeLight": "☀️ Mode clair",
    "fontDecreaseTitle": "Diminuer la taille du texte",
    "fontIncreaseTitle": "Augmenter la taille du texte",
    "loginMissing": "Veuillez saisir l’identifiant et le mot de passe.",
    "loginLoading": "Connexion…",
    "disconnected": "Vous avez été déconnecté.",
    "sessionExpired": "Session expirée. Veuillez vous reconnecter.",
    "syncPdfFound": "PDF trouvés",
    "syncDownloaded": "PDF en cache",
    "syncDownloadedThisRun": "Téléchargés pendant cette mise à jour",
    "syncUnchanged": "Déjà à jour",
    "syncOcrCompleted": "OCR terminés",
    "syncIndexed": "Bulletins indexés",
    "syncIndexedThisRun": "Indexés pendant cette mise à jour",
    "syncErrors": "Erreurs",
    "bulletinsKnown": "{count} bulletin{plural} connu{plural}.",
    "statsSummary": "{bulletins} bulletins · {pages} pages · {firstYear}-{lastYear} · n° {firstNumber}-{lastNumber}",
    "openPdf": "Consulter",
    "notLocal": "Non local",
    "statusIndexed": "Indexé",
    "statusDownloaded": "Téléchargé",
    "statusIndexError": "Erreur d’indexation",
    "statusDownloadError": "Erreur de téléchargement",
    "statusMissingRemote": "Absent en ligne",
    "statusDiscovered": "Découvert",
    "statusUnknown": "Inconnu",
    "searchMissing": "Veuillez saisir au moins un mot clé.",
    "searchLoading": "Recherche…",
    "searchError": "Recherche impossible.",
    "resultsCount": "{total} résultat{plural}. Requête index : {query}",
    "noResult": "Aucun passage trouvé. Essayez un préfixe avec * en mode avancé ou élargissez les filtres.",
    "resultMeta": "Bulletin {number} · {year} · page {page} · source texte : {source}",
    "unknownYear": "année ?",
    "localPdf": "PDF local",
    "apiUnreachable": "Impossible de joindre le serveur local.",
    "auth401": "Identifiant ou mot de passe incorrect.",
    "auth429": "Trop de tentatives. Attendez une minute avant de réessayer.",
    "auth502": "Le site membre n’a pas pu être joint.",
    "authGeneric": "Connexion impossible."
};

const els = {
  pdfDialog: document.getElementById("pdfDialog"),
  pdfTitle: document.getElementById("pdfTitle"),
  pdfSubtitle: document.getElementById("pdfSubtitle"),
  pdfOpenNewTab: document.getElementById("pdfOpenNewTab"),
  pdfCloseButton: document.getElementById("pdfCloseButton"),
  header: document.getElementById("header"),
  app: document.getElementById("app"),
  themeToggle: document.getElementById("themeToggle"),
  fontDecrease: document.getElementById("fontDecrease"),
  fontIncrease: document.getElementById("fontIncrease"),
  logoutButton: document.getElementById("logoutButton"),
  syncMessage: document.getElementById("syncMessage"),
  syncCounters: document.getElementById("syncCounters"),
  syncProgressPanel: document.getElementById("syncProgressPanel"),
  progressBar: document.getElementById("progressBar"),
  progressText: document.getElementById("progressText"),
  etaText: document.getElementById("etaText"),
  currentFileText: document.getElementById("currentFileText"),
  connectivityBadge: document.getElementById("connectivityBadge"),
  sessionRemaining: document.getElementById("sessionRemaining"),
  lastSyncInfo: document.getElementById("lastSyncInfo"),
  readinessMessage: document.getElementById("readinessMessage"),
  searchForm: document.getElementById("searchForm"),
  keywords: document.getElementById("keywords"),
  mode: document.getElementById("mode"),
  limit: document.getElementById("limit"),
  yearFrom: document.getElementById("yearFrom"),
  yearTo: document.getElementById("yearTo"),
  bulletinFrom: document.getElementById("bulletinFrom"),
  bulletinTo: document.getElementById("bulletinTo"),
  searchButton: document.getElementById("searchButton"),
  clearButton: document.getElementById("clearButton"),
  searchMessage: document.getElementById("searchMessage"),
  advancedHelp: document.getElementById("advancedHelp"),
  resultsPanel: document.getElementById("resultsPanel"),
  resultsCount: document.getElementById("resultsCount"),
  results: document.getElementById("results"),
  bulletinsPanel: document.getElementById("bulletinsPanel"),
  bulletinsStatus: document.getElementById("bulletinsStatus"),
  bulletinsBody: document.getElementById("bulletinsBody"),
  stats: document.getElementById("stats"),
};

let pollTimer = null;
let currentLanguage = "fr";
let csrfToken = "";
let lastSyncStatus = null;
let lastBulletins = [];
let lastStats = null;
let lastReadiness = { ready: false };
let pdfViewer = null;
let pdfViewerModule = null;
let pdfOpenGeneration = 0;

window.addEventListener("DOMContentLoaded", async () => {
  initLanguage();
  els.logoutButton.addEventListener("click", handleLogout);
  els.searchForm.addEventListener("submit", handleSearch);
  els.clearButton.addEventListener("click", clearSearch);
  els.pdfCloseButton.addEventListener("click", closePdfViewer);
  els.pdfDialog.addEventListener("close", () => {
    if (els.pdfDialog.open) return;
    pdfOpenGeneration += 1;
    if (pdfViewer) pdfViewer.close();
  });
  document.body.addEventListener("click", handlePdfOpenClick);

  let me = null;
  try {
    me = await api("/api/session", { method: "GET", allow401: true });
  } catch (error) {
    console.warn("Initialisation: impossible de vérifier la session locale.", error);
  }

  if (me && me.authenticated) {
    csrfToken = me.csrfToken || "";
    window.SessionTimer.start({
      expiresAt: me.expiresAt,
      serverTime: me.serverTime,
      durationMinutes: me.durationMinutes,
      element: els.sessionRemaining,
      onExpire: () => window.SessionLifecycle.expire(),
    });
    window.SessionLifecycle.start({sessionKind: "member", token: csrfToken});
    showApp();
    await refreshAll();
    startPolling();
    window.PortalUI.startConnectivity();
  } else {
    window.location.replace("/");
  }
});

function initLanguage() {
  currentLanguage = "fr";
  applyTranslations();
}

function t(key, vars = {}) {
  const value = I18N[key] || key;
  return String(value).replace(/\{(\w+)\}/g, (_, name) => vars[name] ?? "");
}

function applyTranslations() {
  document.documentElement.lang = "fr";
  document.querySelectorAll("[data-i18n]").forEach(node => { node.textContent = t(node.dataset.i18n); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(node => { node.placeholder = t(node.dataset.i18nPlaceholder); });
  document.querySelectorAll("[data-i18n-title]").forEach(node => { node.title = t(node.dataset.i18nTitle); });
  renderAdvancedHelp();
}

function renderAdvancedHelp() {
  const examples = [
    ["carburateur AND starter", t("helpAll")],
    ["\"joint de pare-brise\"", t("helpPhrase")],
    ["frein* OR embrayage*", t("helpPrefix")],
    ["(phare OR ampoule) AND relais", t("helpBool")],
    ["NEAR(phare ampoule, 8)", t("helpNear")],
  ];
  els.advancedHelp.innerHTML = `<p class="help-note">${escapeHtml(t("helpIntro"))}</p>` +
    examples.map(([code, text]) => `<div class="help-example"><code>${escapeHtml(code)}</code><p>${escapeHtml(text)}</p></div>`).join("") +
    `<p class="help-note">${escapeHtml(t("helpNote"))}</p>`;
}

function openLogin() {
  window.location.replace('/');
}

function showApp() {
  els.header.classList.remove("hidden");
  els.app.classList.remove("hidden");
  els.keywords.focus();
}

function hideApp() {
  closePdfViewer();
  els.header.classList.add("hidden");
  els.app.classList.add("hidden");
  els.resultsPanel.classList.add("hidden");
  els.results.innerHTML = "";
  els.bulletinsBody.innerHTML = "";
  if (els.bulletinsPanel) els.bulletinsPanel.classList.add("hidden");
  els.stats.textContent = "";
  if (pollTimer) clearInterval(pollTimer);
  window.PortalUI.stopConnectivity();
  window.SessionLifecycle.stop();
}


async function handleLogout() {
  closePdfViewer();
  window.SessionTimer.stop();
  window.SessionLifecycle.stop();
  window.PortalUI.stopConnectivity();
  try { await api("/api/logout", { method: "POST" }); } catch (_) {}
  window.location.replace("/");
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(refreshStatus, 1800);
  refreshStatus();
}

async function refreshStatus() {
  try {
    const status = await api("/api/bulletins/sync/status", { method: "GET" });
    renderSyncStatus(status);
    await Promise.all([refreshBulletins(), refreshStats()]);
  } catch (error) {
    if (error.status === 401) {
      hideApp();
      openLogin();
    }
  }
}

async function refreshAll() {
  await refreshStatus();
  await refreshBulletins();
  await refreshStats();
}

function renderSyncStatus(status) {
  lastSyncStatus = status;
  const currentReadiness = status.readiness || { ready: !status.running };
  lastReadiness = currentReadiness;
  renderLastSync(currentReadiness.lastSync);
  updateSearchAvailability(currentReadiness, status);
  const processing = Boolean(status.running || status.indexingRunning);
  if (els.syncProgressPanel) {
    els.syncProgressPanel.classList.toggle("hidden", !processing);
  }

  const target = els.readinessMessage || els.syncMessage;
  if (target) {
    const mustWait = processing || !currentReadiness.ready;
    if (mustWait) {
      const type = status.phase === "error" || status.phase === "finished-with-errors" ? "warning" : "info";
      target.className = `message ${type}`;
      const baseMessage = status.indexingRunning
        ? "Indexation des bulletins en cours. La recherche sera réactivée automatiquement à la fin du traitement."
        : (status.running ? (status.message || currentReadiness.message) : (currentReadiness.message || status.message));
      let html = escapeHtml(baseMessage || t("searchBlocked"));
      const activeFile = status.currentIndexFile || status.current;
      if (activeFile) html += `<br><strong>${escapeHtml(activeFile)}</strong>`;
      if (status.errors && status.errors.length) {
        html += `<ul>${status.errors.map(err => `<li>${escapeHtml(err)}</li>`).join("")}</ul>`;
      }
      target.innerHTML = html;
      target.classList.remove("hidden");
    } else {
      target.classList.add("hidden");
      target.textContent = "";
    }
  }

  if (els.progressBar && els.progressText) {
    const totalSteps = Number(status.totalSteps || 0);
    const completedSteps = Number(status.completedSteps || 0);
    let pct = 0;
    if (status.indexingRunning) {
      pct = Math.max(0, Math.min(100, Number(status.indexProgressPercent || 0)));
    } else if (totalSteps > 0) {
      pct = status.running ? Math.min(100, Math.round((completedSteps / totalSteps) * 100)) : 100;
    } else if (!processing) {
      pct = 100;
    }
    els.progressBar.style.width = `${pct}%`;
    els.progressText.textContent = `${pct}%`;
    const complete = pct >= 100;
    els.progressBar.classList.toggle("is-complete", complete);
    els.progressBar.classList.toggle("is-active", processing && !complete);
  }
  if (els.etaText) {
    els.etaText.textContent = status.running && !status.indexingRunning ? estimatedRemainingLabel(status) : "";
  }
  if (els.currentFileText) {
    const activeFile = status.currentIndexFile || status.current;
    els.currentFileText.textContent = processing && activeFile ? `Fichier en cours : ${activeFile}` : "";
  }
  if (els.syncCounters) {
    const discovered = status.discovered || status.knownBulletins || 0;
    const cached = status.localPdfCount ?? status.downloaded ?? 0;
    const downloadedThisRun = status.downloadedThisRun ?? 0;
    const indexedTotal = status.indexedBulletins ?? status.indexed ?? 0;
    const indexedThisRun = status.indexedThisRun ?? 0;
    els.syncCounters.innerHTML = [
      [t("syncPdfFound"), discovered],
      [t("syncDownloaded"), cached],
      [t("syncDownloadedThisRun"), downloadedThisRun],
      [t("syncUnchanged"), status.unchanged],
      [t("syncOcrCompleted"), status.ocrCompleted],
      [t("syncIndexed"), indexedTotal],
      [t("syncIndexedThisRun"), indexedThisRun],
      [t("syncErrors"), status.failed],
    ].map(([label, value]) => `<span class="counter">${escapeHtml(label)} : <strong>${value || 0}</strong></span>`).join("");
  }
}

function renderLastSync(lastSync) {
  if (!els.lastSyncInfo) return;
  const value = lastSync && (lastSync.finished_at || lastSync.started_at);
  if (!value) {
    els.lastSyncInfo.textContent = t("lastSyncUnknown");
    return;
  }
  els.lastSyncInfo.textContent = t("lastSyncLabel", { value: formatDateTime(value) });
}

function formatDateTime(value) {
  const date = new Date(String(value).replace(" ", "T") + (String(value).endsWith("Z") ? "" : "Z"));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Europe/Paris",
  }).format(date);
}

function updateSearchAvailability(readiness, status = {}) {
  const waiting = Boolean(status.processingRunning || status.running || status.indexingRunning);
  [els.keywords, els.mode, els.limit, els.yearFrom, els.yearTo, els.bulletinFrom, els.bulletinTo, els.searchButton].forEach(node => {
    if (node) node.disabled = waiting;
  });
  els.searchForm.classList.toggle("search-disabled", waiting);
}

function estimatedRemainingLabel(status) {
  const total = Number(status.totalSteps || 0);
  const completed = Number(status.completedSteps || 0);
  const startedAt = Number(status.startedAt || 0);
  if (!total || !completed || !startedAt) return t("syncEtaUnknown");
  const elapsedSeconds = Math.max(1, (Date.now() / 1000) - startedAt);
  const remainingSteps = Math.max(0, total - completed);
  const secondsPerStep = elapsedSeconds / completed;
  const remainingSeconds = Math.round(remainingSteps * secondsPerStep);
  if (!Number.isFinite(remainingSeconds) || remainingSeconds < 1) return t("syncEtaUnknown");
  return t("syncEta", { time: formatDuration(remainingSeconds) });
}

function formatDuration(seconds) {
  const safe = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const secs = safe % 60;
  if (hours > 0) return `${hours} h ${String(minutes).padStart(2, "0")} min`;
  if (minutes > 0) return `${minutes} min ${String(secs).padStart(2, "0")} s`;
  return `${secs} s`;
}

async function refreshBulletins() {
  const data = await api("/api/bulletins/list", { method: "GET" });
  renderBulletins(data.bulletins || []);
}

function renderBulletins(bulletins) {
  lastBulletins = bulletins;
  if (els.bulletinsPanel) els.bulletinsPanel.classList.toggle("hidden", bulletins.length === 0);
  const plural = bulletins.length > 1 ? "s" : "";
  els.bulletinsStatus.textContent = t("bulletinsKnown", { count: bulletins.length, plural });
  els.bulletinsBody.innerHTML = bulletins.map(renderBulletinRow).join("");
  updateBulletinRangeFromBulletins(bulletins);
}

async function refreshStats() {
  try {
    const data = await api("/api/bulletins/stats", { method: "GET" });
    renderStats(data.summary || {});
  } catch (_) {}
}

function renderStats(s) {
  lastStats = s;
  const firstNumber = s.firstNumber ?? 1;
  const computedMax = Math.max(Number(s.lastNumber || 0), Number(s.bulletins || 0), 99);
  els.stats.textContent = t("statsSummary", {
    bulletins: s.bulletins || 0,
    pages: s.pages || 0,
    firstYear: s.firstYear || "?",
    lastYear: s.lastYear || "?",
    firstNumber,
    lastNumber: computedMax,
  });
  els.bulletinFrom.min = String(Math.max(1, Number(firstNumber || 1)));
  els.bulletinTo.max = String(computedMax);
  els.bulletinTo.placeholder = String(computedMax);
}

function updateBulletinRangeFromBulletins(bulletins) {
  const numbers = bulletins.map(b => Number(b.number)).filter(Number.isFinite);
  const maxNumber = numbers.length ? Math.max(...numbers) : 0;
  const computedMax = Math.max(maxNumber, bulletins.length, 99);
  els.bulletinTo.max = String(computedMax);
  els.bulletinTo.placeholder = String(computedMax);
}

function renderBulletinRow(b) {
  const number = b.number ?? "";
  const title = escapeHtml(b.title || b.filename || "Bulletin");
  const year = b.year ?? "";
  const pages = b.pages || 0;
  const statusCode = String(b.status || "unknown");
  const statusLabels = {
    indexed: t("statusIndexed"),
    downloaded: t("statusDownloaded"),
    "index-error": t("statusIndexError"),
    "download-error": t("statusDownloadError"),
    "missing-remote": t("statusMissingRemote"),
    discovered: t("statusDiscovered"),
    unknown: t("statusUnknown")
  };
  const status = escapeHtml(statusLabels[statusCode] || statusCode);
  const pdfUrl = escapeHtml(b.pdfUrl || "#");
  const canOpen = Boolean(b.pdfUrl);
  return `
    <tr>
      <td data-label="${escapeHtml(t("tableNo"))}">${number}</td>
      <td data-label="${escapeHtml(t("tableTitle"))}"><a href="${pdfUrl}" data-open-pdf="${pdfUrl}" data-pdf-title="${title}" target="_blank" rel="noopener noreferrer">${title}</a><br><span class="muted">${escapeHtml(b.filename || "")}</span></td>
      <td data-label="${escapeHtml(t("tableYear"))}">${year}</td>
      <td data-label="${escapeHtml(t("tablePages"))}">${pages}</td>
      <td data-label="${escapeHtml(t("tableStatus"))}"><span class="badge status-${escapeHtml(statusCode)}">${status}</span></td>
      <td data-label="${escapeHtml(t("tablePdf"))}">${canOpen ? `<button type="button" class="button-ghost compact" data-open-pdf="${pdfUrl}" data-pdf-title="${title}">${escapeHtml(t("openPdf"))}</button>` : `<span class="muted">${escapeHtml(t("notLocal"))}</span>`}</td>
    </tr>`;
}

async function handleSearch(event) {
  event.preventDefault();
  clearMessage(els.searchMessage);
  const keywords = els.keywords.value.trim();
  if (!keywords) {
    showMessage(els.searchMessage, t("searchMissing"), "error");
    return;
  }
  if (lastReadiness && !lastReadiness.ready) {
    showMessage(els.searchMessage, lastReadiness.message || t("searchBlocked"), "warning");
    return;
  }
  setLoading(els.searchButton, true, t("searchLoading"));
  try {
    const payload = {
      keywords,
      mode: els.mode.value,
      limit: Number(els.limit.value || 50),
      yearFrom: numberOrNull(els.yearFrom.value),
      yearTo: numberOrNull(els.yearTo.value),
      bulletinFrom: numberOrNull(els.bulletinFrom.value),
      bulletinTo: numberOrNull(els.bulletinTo.value),
    };
    const data = await api("/api/bulletins/search", { method: "POST", body: payload });
    renderResults(data);
  } catch (error) {
    showMessage(els.searchMessage, error.message || t("searchError"), "error");
  } finally {
    setLoading(els.searchButton, false, t("searchButton"));
  }
}

function renderResults(data) {
  els.resultsPanel.classList.remove("hidden");
  const total = Number(data.total || 0);
  const found = data.results || [];
  const plural = total > 1 ? "s" : "";
  els.resultsCount.textContent = t("resultsCount", { total, plural, query: data.query || "" });
  if (!found.length) {
    els.results.innerHTML = `<div class="result-item">${escapeHtml(t("noResult"))}</div>`;
    return;
  }
  els.results.innerHTML = found.map(renderResultItem).join("");
}

function renderResultItem(item) {
  const title = escapeHtml(item.bulletinTitle || item.filename || "Bulletin");
  const number = item.number ? `n°${item.number}` : "n° ?";
  const year = item.year || t("unknownYear");
  const page = item.page || "?";
  const source = escapeHtml(item.source || "");
  const excerpt = renderExcerpt(item.excerpt || "");
  const pdfUrl = escapeHtml(item.pdfUrl || "#");
  const meta = t("resultMeta", { number, year, page, source });
  return `
    <article class="result-item">
      <div class="result-topline">
        <h3 class="result-title"><a href="${pdfUrl}" data-open-pdf="${pdfUrl}" data-pdf-title="${title} — page ${page}" target="_blank" rel="noopener noreferrer">${title}</a></h3>
        <button type="button" class="button-ghost compact" data-open-pdf="${pdfUrl}" data-pdf-title="${title} — page ${page}">${escapeHtml(t("localPdf"))}</button>
      </div>
      <div class="result-meta">${escapeHtml(meta)}</div>
      <p>${excerpt}</p>
    </article>`;
}

function renderExcerpt(value) {
  return escapeHtml(value)
    .replaceAll("[[[H]]]", "<mark>")
    .replaceAll("[[[/H]]]", "</mark>");
}

function handlePdfOpenClick(event) {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const button = event.target.closest("[data-open-pdf]");
  if (!button) return;
  event.preventDefault();
  openPdfViewer(button.dataset.openPdf, button.dataset.pdfTitle || t("localPdf"));
}

async function openPdfViewer(url, title) {
  if (!url || url === "#") return;
  const generation = ++pdfOpenGeneration;
  if (pdfViewer) pdfViewer.close();
  els.pdfTitle.textContent = t("pdfTitle");
  els.pdfSubtitle.textContent = title || "";
  els.pdfOpenNewTab.removeAttribute("href");
  const status = document.getElementById("pdfStatus");
  status.textContent = "Chargement du bulletin…";
  status.className = "pdf-status message info";
  if (!els.pdfDialog.open) els.pdfDialog.showModal();
  try {
    pdfViewerModule ||= import("/static/bulletins/pdf_viewer.mjs?v=1.1.31");
    const {BulletinPdfViewer} = await pdfViewerModule;
    if (generation !== pdfOpenGeneration || !els.pdfDialog.open) return;
    pdfViewer ||= new BulletinPdfViewer(els.pdfDialog, () => window.SessionLifecycle.expire());
    await pdfViewer.open(url);
  } catch {
    if (generation !== pdfOpenGeneration || !els.pdfDialog.open) return;
    pdfViewerModule = null;
    status.textContent = "La visionneuse n’a pas pu démarrer. Actualisez cette page puis réessayez.";
    status.className = "pdf-status message error";
  }
}

function closePdfViewer() {
  pdfOpenGeneration += 1;
  if (pdfViewer) pdfViewer.close();
  if (els.pdfDialog.open) els.pdfDialog.close();
}

function clearSearch() {
  els.searchForm.reset();
  els.resultsPanel.classList.add("hidden");
  els.results.innerHTML = "";
  clearMessage(els.searchMessage);
  els.keywords.focus();
}

async function api(url, options = {}) {
  const fetchOptions = { method: options.method || "GET", credentials: "include", headers: { "Accept": "application/json" } };
  if (!["GET", "HEAD", "OPTIONS"].includes(fetchOptions.method.toUpperCase()) && csrfToken) fetchOptions.headers["X-CSRF-Token"] = csrfToken;
  if (options.body !== undefined) {
    fetchOptions.headers["Content-Type"] = "application/json";
    fetchOptions.body = JSON.stringify(options.body);
  }
  let response;
  try { response = await fetch(url, fetchOptions); }
  catch (_) { throw new ApiError(0, t("apiUnreachable")); }
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) {
    if (options.allow401 && response.status === 401) return data;
    throw new ApiError(response.status, data.message || `Erreur HTTP ${response.status}`);
  }
  return data;
}

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}


function showMessage(el, text, type) {
  el.textContent = text;
  el.className = `message ${type}`;
}

function clearMessage(el) {
  el.textContent = "";
  el.className = "message hidden";
}

function setLoading(button, loading, text) {
  button.disabled = loading;
  button.textContent = text;
}

function numberOrNull(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
