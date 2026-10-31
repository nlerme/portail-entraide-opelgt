import {getDocument, GlobalWorkerOptions} from '../vendor/pdfjs-6.4.299/pdf.min.mjs';

const ASSETS = '/static/vendor/pdfjs-6.4.299/';
const MAX_PIXELS = 4_000_000;
GlobalWorkerOptions.workerSrc = `${ASSETS}pdf.worker.min.mjs`;

function localPdf(value) {
  const url = new URL(value, window.location.href);
  if (url.origin !== window.location.origin || url.username || url.password ||
      !/^\/api\/bulletins\/(?:pdf\/\d+|pdf-file\/[^/]+)$/.test(url.pathname)) throw new Error('Adresse de bulletin invalide.');
  const page = Number(new URLSearchParams(url.hash.slice(1)).get('page'));
  url.hash = '';
  return {url: url.href, page: Number.isSafeInteger(page) && page > 0 ? page : 1};
}

export class BulletinPdfViewer {
  constructor(dialog, onSessionExpired) {
    const element = id => dialog.querySelector(`#${id}`);
    this.dialog = dialog;
    this.viewport = element('pdfViewport');
    this.status = element('pdfStatus');
    this.pageInput = element('pdfPageNumber');
    this.pageCount = element('pdfPageCount');
    this.zoomInput = element('pdfZoom');
    this.newTab = element('pdfOpenNewTab');
    this.previousMatch = element('pdfPreviousMatch');
    this.nextMatch = element('pdfNextMatch');
    this.matchCount = element('pdfMatchCount');
    this.onSessionExpired = onSessionExpired;
    this.generation = 0;
    this.layoutGeneration = 0;
    this.document = null;
    this.loadingTask = null;
    this.renderTask = null;
    this.rendering = false;
    this.states = [];
    this.near = new Set();
    this.matches = [];
    this.activeMatch = null;
    this.controllers = new Set();
    this.pageNumber = 1;
    this.zoom = 1;
    this.searching = false;
    this.search = null;
    this.resizeTimer = null;
    this.scrollFrame = null;
    this.pageInput.addEventListener('change', () => this.goTo(Number(this.pageInput.value)));
    this.pageInput.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); this.goTo(Number(this.pageInput.value)); }
    });
    this.zoomInput.addEventListener('change', () => { this.zoom = Number(this.zoomInput.value) || 1; this.layout(); });
    this.previousMatch.addEventListener('click', () => this.moveMatch(-1));
    this.nextMatch.addEventListener('click', () => this.moveMatch(1));
    this.viewport.addEventListener('scroll', () => {
      if (this.scrollFrame !== null) return;
      this.scrollFrame = requestAnimationFrame(() => { this.scrollFrame = null; this.refreshVisible(); });
    }, {passive: true});
    for (const event of ['wheel', 'touchstart', 'pointerdown', 'keydown']) {
      this.viewport.addEventListener(event, () => { this.userInteracted = true; }, {passive: true});
    }
    this.lastWidth = 0;
    this.resizeObserver = new ResizeObserver(() => {
      const width = this.viewport.clientWidth;
      if (!width || width === this.lastWidth) return;
      this.lastWidth = width;
      clearTimeout(this.resizeTimer);
      this.resizeTimer = setTimeout(() => { if (this.dialog.open && this.document) this.layout(); }, 120);
    });
    this.resizeObserver.observe(this.viewport);
    this.controls();
  }

  message(text, error = false) {
    this.status.textContent = text;
    this.status.className = `pdf-status message ${error ? 'error' : 'info'}${text ? '' : ' hidden'}`;
  }

  controls() {
    const pages = this.document?.numPages || 0;
    this.pageInput.disabled = !pages;
    this.zoomInput.disabled = !pages;
    if (window.document.activeElement !== this.pageInput) this.pageInput.value = String(this.pageNumber);
    this.pageInput.max = String(pages || 1);
    this.pageCount.textContent = `/ ${pages}`;
    this.previousMatch.disabled = this.nextMatch.disabled = this.searching || !this.matches.length;
    const current = this.matches.indexOf(this.activeMatch);
    this.matchCount.textContent = this.searching ? `Repérage… ${this.matches.length}` : !this.search ? 'Aucune recherche' :
      current >= 0 ? `Occurrence ${current + 1} / ${this.matches.length}` : `${this.matches.length} occurrence(s)`;
  }

  async open(value, search = null) {
    this.close();
    const generation = ++this.generation;
    this.search = search;
    this.searching = Boolean(search);
    this.userInteracted = false;
    this.controls();
    this.message('Chargement du bulletin…');
    this.viewport.setAttribute('aria-busy', 'true');
    this.viewport.dataset.state = 'loading';
    try {
      const target = localPdf(value);
      this.url = target.url;
      this.newTab.href = `${target.url}#page=${target.page}`;
      const task = getDocument({
        url: target.url, withCredentials: true, cMapUrl: `${ASSETS}cmaps/`, cMapPacked: true,
        standardFontDataUrl: `${ASSETS}standard_fonts/`, wasmUrl: `${ASSETS}wasm/`,
        isEvalSupported: false, disableFontFace: true, disableAutoFetch: true, disableStream: true,
        canvasMaxAreaInBytes: 32 * 1024 * 1024,
      });
      this.loadingTask = task;
      task.onProgress = progress => {
        if (generation === this.generation && progress.total) this.message(`Chargement du bulletin… ${Math.min(99, Math.floor(progress.loaded / progress.total * 100))} %`);
      };
      const document = await task.promise;
      if (generation !== this.generation || !this.dialog.open) return;
      task.onProgress = null;
      this.document = document;
      this.pageNumber = Math.min(target.page, document.numPages);
      const fragment = window.document.createDocumentFragment();
      // Page metadata is small; canvases are allocated only near the viewport.
      for (let number = 1; number <= document.numPages; number += 1) {
        const page = await document.getPage(number);
        if (generation !== this.generation) return;
        const original = page.getViewport({scale: 1});
        const sheet = window.document.createElement('section');
        sheet.className = 'pdf-sheet'; sheet.dataset.page = String(number);
        sheet.setAttribute('aria-label', `Page ${number} sur ${document.numPages}`);
        const layer = window.document.createElement('div'); layer.className = 'pdf-highlight-layer';
        sheet.append(layer); fragment.append(sheet);
        this.states.push({number, sheet, layer, original, canvas: null, rendered: false, failed: false});
      }
      if (generation !== this.generation) return;
      this.viewport.replaceChildren(fragment);
      this.layout(false);
      this.goTo(Math.min(target.page, document.numPages), false);
      this.message('');
      if (search && /\/pdf\/\d+$/.test(new URL(target.url).pathname)) {
        this.findMatches(search, target, generation);
      } else { this.searching = false; this.controls(); }
    } catch (error) {
      if (generation !== this.generation || !this.dialog.open) return;
      this.viewport.setAttribute('aria-busy', 'false'); this.viewport.dataset.state = 'error';
      this.searching = false; this.controls();
      if (error.status === 401) { this.message('Session expirée. Veuillez vous reconnecter.', true); this.onSessionExpired(); }
      else this.message(error.name === 'PasswordException' ? 'Ce bulletin est protégé par un mot de passe. Utilisez « Nouvel onglet ».' :
        'Impossible de charger ce bulletin. Vérifiez la connexion au portail puis réessayez.', true);
      const task = this.loadingTask; this.loadingTask = null;
      if (task) task.destroy().catch(() => {});
    }
  }

  layout(preserve = true) {
    if (!this.document || !this.states.length) return;
    const anchor = this.states[this.pageNumber - 1];
    const fraction = preserve && anchor.height ? (this.viewport.scrollTop - anchor.sheet.offsetTop) / anchor.height : 0;
    this.layoutGeneration += 1;
    if (this.renderTask) this.renderTask.cancel();
    const padding = getComputedStyle(this.viewport);
    const width = Math.max(100, this.viewport.clientWidth - parseFloat(padding.paddingLeft) - parseFloat(padding.paddingRight) - 2) * this.zoom;
    for (const state of this.states) {
      if (state.canvas) state.canvas.remove();
      state.canvas = null; state.rendered = false; state.failed = false;
      state.sheet.classList.remove('is-rendered');
      state.width = Math.floor(width); state.height = Math.floor(width * state.original.height / state.original.width);
      state.sheet.style.width = `${state.width}px`; state.sheet.style.height = `${state.height}px`;
    }
    this.viewport.scrollTop = anchor.sheet.offsetTop + fraction * anchor.height;
    this.refreshVisible();
  }

  goTo(value, interacted = true) {
    if (!this.document) return;
    this.pageNumber = Math.min(this.document.numPages, Math.max(1, Number.isFinite(value) ? Math.trunc(value) : this.pageNumber));
    if (interacted) this.userInteracted = true;
    this.viewport.scrollTop = this.states[this.pageNumber - 1].sheet.offsetTop;
    this.refreshVisible();
  }

  refreshVisible() {
    if (!this.document || !this.states.length) return;
    const top = this.viewport.scrollTop, height = this.viewport.clientHeight;
    this.near = new Set(this.states.filter(state => state.sheet.offsetTop + state.height >= top - height && state.sheet.offsetTop <= top + height * 2));
    const current = this.states.find(state => state.sheet.offsetTop + state.height >= top + height / 2);
    this.pageNumber = (current || this.states.at(-1)).number;
    this.controls();
    this.scheduleRender();
    this.evict();
  }

  evict() {
    const resident = this.states.filter(state => state.rendered);
    let pixels = resident.reduce((sum, state) => sum + state.canvas.width * state.canvas.height, 0), count = resident.length;
    for (const state of resident.filter(state => !this.near.has(state)).sort((a, b) => Math.abs(b.number - this.pageNumber) - Math.abs(a.number - this.pageNumber))) {
      if (count <= 6 && pixels <= 12_000_000) break;
      pixels -= state.canvas.width * state.canvas.height; count -= 1;
      state.canvas.width = state.canvas.height = 0; state.canvas.remove(); state.canvas = null; state.rendered = false;
      state.sheet.classList.remove('is-rendered');
    }
  }

  async scheduleRender() {
    if (this.rendering || !this.document || !this.dialog.open) return;
    this.rendering = true;
    try {
      while (this.document && this.dialog.open) {
        const state = [...this.near].filter(value => !value.rendered && !value.failed).sort((a, b) => Math.abs(a.number - this.pageNumber) - Math.abs(b.number - this.pageNumber))[0];
        if (!state) break;
        await this.renderPage(state);
        this.evict();
      }
    } finally { this.rendering = false; }
  }

  async renderPage(state) {
    const document = this.document, generation = this.generation, layout = this.layoutGeneration;
    let page = null;
    try {
      page = await document.getPage(state.number);
      if (generation !== this.generation || layout !== this.layoutGeneration) return;
      const canvas = window.document.createElement('canvas');
      canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', `Page ${state.number} sur ${document.numPages} du bulletin`);
      const viewport = page.getViewport({scale: state.width / state.original.width});
      const scale = Math.min(window.devicePixelRatio || 1, 2, 4096 / viewport.width, 4096 / viewport.height,
        Math.sqrt(MAX_PIXELS / (viewport.width * viewport.height)));
      canvas.width = Math.max(1, Math.floor(viewport.width * scale)); canvas.height = Math.max(1, Math.floor(viewport.height * scale));
      canvas.style.width = `${state.width}px`; canvas.style.height = `${state.height}px`;
      const context = canvas.getContext('2d', {alpha: false});
      if (!context) throw new Error('Affichage non disponible.');
      const task = page.render({canvasContext: context, viewport, transform: [scale, 0, 0, scale, 0, 0], background: 'rgb(255,255,255)'});
      this.renderTask = task;
      await task.promise;
      if (generation !== this.generation || layout !== this.layoutGeneration) return;
      state.canvas = canvas; state.sheet.prepend(canvas); state.rendered = true; state.sheet.classList.add('is-rendered');
      this.viewport.dataset.state = 'ready'; this.viewport.setAttribute('aria-busy', 'false');
    } catch (error) {
      if (generation !== this.generation || layout !== this.layoutGeneration || error.name === 'RenderingCancelledException') return;
      state.failed = true;
      this.viewport.setAttribute('aria-busy', 'false');
      this.message(`La page ${state.number} n’a pas pu être affichée. Fermez puis rouvrez le bulletin pour réessayer.`, true);
    } finally { this.renderTask = null; if (page) page.cleanup(); }
  }

  async requestMatches(url, payload, csrf, generation) {
    const controller = new AbortController(); this.controllers.add(controller);
    const timer = setTimeout(() => controller.abort(), 55000);
    try {
      const response = await fetch(url, {method: 'POST', credentials: 'include', cache: 'no-store', signal: controller.signal,
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(payload)});
      if (generation !== this.generation) throw new Error('Consultation fermée.');
      if (response.status === 401) { this.onSessionExpired(); throw new Error('Session expirée.'); }
      if (!response.ok) throw new Error('Repérage indisponible.');
      return await response.json();
    } finally { clearTimeout(timer); this.controllers.delete(controller); }
  }

  async findMatches(search, target, generation) {
    const endpoint = `${target.url}/highlights`, payload = {keywords: search.keywords, mode: search.mode};
    let failures = 0;
    try {
      const data = await this.requestMatches(endpoint, payload, search.csrf, generation);
      const pages = data.pages.filter(page => Number.isInteger(page) && page > 0 && page <= this.states.length);
      pages.sort((a, b) => (a === target.page ? -1 : b === target.page ? 1 : a - b));
      for (const page of pages) {
        if (generation !== this.generation) return;
        try {
          const result = await this.requestMatches(endpoint, {...payload, page}, search.csrf, generation);
          if (generation !== this.generation) return;
          const state = this.states[page - 1];
          for (const item of result.occurrences) {
            const rects = item.rects.filter(rect => Array.isArray(rect) && rect.length === 4 && rect.every(Number.isFinite));
            if (!rects.length) continue;
            const match = {state, rects, nodes: []};
            for (const rect of rects) {
              const mark = window.document.createElement('span'); mark.className = 'pdf-highlight';
              const [left, top, right, bottom] = rect.map(value => Math.max(0, Math.min(1, value)));
              mark.style.left = `${left * 100}%`; mark.style.top = `${top * 100}%`;
              mark.style.width = `${Math.max(.001, right - left) * 100}%`; mark.style.height = `${Math.max(.001, bottom - top) * 100}%`;
              state.layer.append(mark); match.nodes.push(mark);
            }
            this.matches.push(match);
          }
          this.matches.sort((a, b) => a.state.number - b.state.number || a.rects[0][1] - b.rects[0][1] || a.rects[0][0] - b.rects[0][0]);
          if (!result.occurrences.length) failures += 1;
          if (!this.activeMatch && page === target.page && this.matches.length) this.activate(this.matches.find(match => match.state.number === page), !this.userInteracted);
          this.controls();
        } catch {
          if (generation !== this.generation) return;
          failures += 1;
        }
      }
      if (!this.activeMatch && this.matches.length) this.activate(this.matches.find(match => match.state.number >= target.page) || this.matches[0], !this.userInteracted);
    } catch {
      if (generation !== this.generation) return;
      failures += 1;
    } finally {
      if (generation === this.generation) {
        this.searching = false; this.controls();
        if (failures) this.message(`Le surlignage n’a pas pu être positionné sur ${failures} page(s). Le bulletin reste consultable.`, true);
      }
    }
  }

  activate(match, scroll = true) {
    if (!match) return;
    if (this.activeMatch) this.activeMatch.nodes.forEach(node => node.classList.remove('is-current'));
    this.activeMatch = match; match.nodes.forEach(node => node.classList.add('is-current'));
    if (scroll) {
      const rect = match.rects[0];
      this.viewport.scrollTop = match.state.sheet.offsetTop + (rect[1] + rect[3]) / 2 * match.state.height - this.viewport.clientHeight / 2;
      this.viewport.scrollLeft = Math.max(0, (rect[0] + rect[2]) / 2 * match.state.width - this.viewport.clientWidth / 2);
      this.refreshVisible();
    }
    this.controls();
  }

  moveMatch(direction) {
    if (this.searching || !this.matches.length) return;
    this.userInteracted = true;
    const current = this.matches.indexOf(this.activeMatch);
    this.activate(this.matches[(current + direction + this.matches.length) % this.matches.length]);
  }

  close() {
    this.generation += 1; this.layoutGeneration += 1;
    clearTimeout(this.resizeTimer);
    if (this.scrollFrame !== null) cancelAnimationFrame(this.scrollFrame);
    this.scrollFrame = null;
    for (const controller of this.controllers) controller.abort();
    this.controllers.clear();
    if (this.renderTask) this.renderTask.cancel();
    const task = this.loadingTask; this.loadingTask = null; this.document = null;
    if (task) task.destroy().catch(() => {});
    this.states = []; this.near.clear(); this.matches = []; this.activeMatch = null; this.search = null; this.searching = false;
    this.viewport.replaceChildren(); this.viewport.scrollTop = this.viewport.scrollLeft = 0;
    this.viewport.dataset.state = 'closed'; this.viewport.setAttribute('aria-busy', 'false');
    this.newTab.removeAttribute('href'); this.pageNumber = 1; this.zoom = 1; this.zoomInput.value = '1';
    this.controls(); this.message('');
  }
}
