import {getDocument, GlobalWorkerOptions} from '../vendor/pdfjs-6.4.299/pdf.min.mjs';

const ASSETS = '/static/vendor/pdfjs-6.4.299/';
const MAX_PIXELS = 8_000_000;
GlobalWorkerOptions.workerSrc = `${ASSETS}pdf.worker.min.mjs`;

function localPdf(value) {
  const url = new URL(value, window.location.href);
  if (url.origin !== window.location.origin || url.username || url.password ||
      !/^\/api\/bulletins\/(?:pdf\/\d+|pdf-file\/[^/]+)$/.test(url.pathname)) {
    throw new Error('Adresse de bulletin invalide.');
  }
  const page = Number(new URLSearchParams(url.hash.slice(1)).get('page'));
  url.hash = '';
  return {url: url.href, page: Number.isSafeInteger(page) && page > 0 ? page : 1};
}

export class BulletinPdfViewer {
  constructor(dialog, onSessionExpired) {
    const element = id => dialog.querySelector(`#${id}`);
    this.dialog = dialog;
    this.viewport = element('pdfViewport');
    this.canvas = element('pdfCanvas');
    this.status = element('pdfStatus');
    this.previous = element('pdfPrevious');
    this.next = element('pdfNext');
    this.pageInput = element('pdfPageNumber');
    this.pageCount = element('pdfPageCount');
    this.zoomInput = element('pdfZoom');
    this.newTab = element('pdfOpenNewTab');
    this.onSessionExpired = onSessionExpired;
    this.loadGeneration = 0;
    this.renderGeneration = 0;
    this.document = null;
    this.loadingTask = null;
    this.renderTask = null;
    this.renderDone = Promise.resolve();
    this.pageNumber = 1;
    this.zoom = 1;
    this.resizeTimer = null;
    this.previous.addEventListener('click', () => this.goTo(this.pageNumber - 1));
    this.next.addEventListener('click', () => this.goTo(this.pageNumber + 1));
    this.pageInput.addEventListener('change', () => this.goTo(Number(this.pageInput.value)));
    this.pageInput.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        this.goTo(Number(this.pageInput.value));
      }
    });
    this.zoomInput.addEventListener('change', () => {
      this.zoom = Number(this.zoomInput.value) || 1;
      this.render();
    });
    this.lastWidth = 0;
    this.resizeObserver = new ResizeObserver(() => {
      const width = this.viewport.clientWidth;
      if (!width || width === this.lastWidth) return;
      this.lastWidth = width;
      clearTimeout(this.resizeTimer);
      this.resizeTimer = setTimeout(() => {
        if (this.dialog.open && this.document) this.render();
      }, 120);
    });
    this.resizeObserver.observe(this.viewport);
  }

  message(text, error = false) {
    this.status.textContent = text;
    this.status.className = `pdf-status message ${error ? 'error' : 'info'}${text ? '' : ' hidden'}`;
  }

  controls() {
    const pages = this.document ? this.document.numPages : 0;
    this.pageInput.disabled = !pages;
    this.zoomInput.disabled = !pages;
    this.previous.disabled = !pages || this.pageNumber <= 1;
    this.next.disabled = !pages || this.pageNumber >= pages;
    this.pageInput.value = String(this.pageNumber);
    this.pageInput.max = String(pages || 1);
    this.pageCount.textContent = `/ ${pages}`;
  }

  async open(value) {
    this.close();
    const generation = ++this.loadGeneration;
    this.message('Chargement du bulletin…');
    this.viewport.setAttribute('aria-busy', 'true');
    this.viewport.dataset.state = 'loading';
    try {
      const target = localPdf(value);
      this.newTab.href = `${target.url}#page=${target.page}`;
      const task = getDocument({
        url: target.url,
        withCredentials: true,
        cMapUrl: `${ASSETS}cmaps/`,
        cMapPacked: true,
        standardFontDataUrl: `${ASSETS}standard_fonts/`,
        wasmUrl: `${ASSETS}wasm/`,
        isEvalSupported: false,
        disableFontFace: true,
        disableAutoFetch: true,
        disableStream: true,
        canvasMaxAreaInBytes: 32 * 1024 * 1024,
      });
      this.loadingTask = task;
      task.onProgress = progress => {
        if (generation !== this.loadGeneration || !progress.total) return;
        this.message(`Chargement du bulletin… ${Math.min(99, Math.floor(progress.loaded / progress.total * 100))} %`);
      };
      const document = await task.promise;
      if (generation !== this.loadGeneration || !this.dialog.open) return;
      task.onProgress = null;
      this.document = document;
      this.pageNumber = Math.min(target.page, document.numPages);
      this.controls();
      await this.render();
    } catch (error) {
      if (generation !== this.loadGeneration || !this.dialog.open) return;
      this.viewport.setAttribute('aria-busy', 'false');
      this.viewport.dataset.state = 'error';
      this.controls();
      if (error.status === 401) {
        this.message('Session expirée. Veuillez vous reconnecter.', true);
        this.onSessionExpired();
      } else if (error.name === 'PasswordException') {
        this.message('Ce bulletin est protégé par un mot de passe. Utilisez « Nouvel onglet » pour le consulter.', true);
      } else {
        this.message('Impossible de charger ce bulletin. Vérifiez la connexion au portail puis réessayez.', true);
      }
      const task = this.loadingTask;
      this.loadingTask = null;
      if (task) task.destroy().catch(() => {});
    }
  }

  goTo(value) {
    if (!this.document) return;
    const page = Math.min(this.document.numPages, Math.max(1, Number.isFinite(value) ? Math.trunc(value) : this.pageNumber));
    this.pageInput.value = String(page);
    if (page === this.pageNumber) return;
    this.pageNumber = page;
    this.viewport.scrollTop = 0;
    this.viewport.scrollLeft = 0;
    this.controls();
    this.render();
  }

  async render() {
    const document = this.document;
    if (!document || !this.dialog.open) return;
    const generation = ++this.renderGeneration;
    const pageNumber = this.pageNumber;
    const previousTask = this.renderTask;
    if (previousTask) previousTask.cancel();
    this.viewport.setAttribute('aria-busy', 'true');
    this.viewport.dataset.state = 'rendering';
    this.message(`Affichage de la page ${pageNumber}…`);
    this.canvas.classList.add('hidden');
    let page = null;
    try {
      await this.renderDone;
      if (generation !== this.renderGeneration || document !== this.document) return;
      page = await document.getPage(pageNumber);
      if (generation !== this.renderGeneration || document !== this.document) return;
      const original = page.getViewport({scale: 1});
      const padding = getComputedStyle(this.viewport);
      const width = Math.max(100, this.viewport.clientWidth - parseFloat(padding.paddingLeft) - parseFloat(padding.paddingRight) - 2);
      const viewport = page.getViewport({scale: width / original.width * this.zoom});
      const outputScale = Math.min(window.devicePixelRatio || 1, 2,
        4096 / viewport.width, 4096 / viewport.height,
        Math.sqrt(MAX_PIXELS / (viewport.width * viewport.height)));
      this.canvas.width = Math.max(1, Math.floor(viewport.width * outputScale));
      this.canvas.height = Math.max(1, Math.floor(viewport.height * outputScale));
      this.canvas.style.width = `${Math.floor(viewport.width)}px`;
      this.canvas.style.height = `${Math.floor(viewport.height)}px`;
      this.canvas.setAttribute('aria-label', `Page ${pageNumber} sur ${document.numPages} du bulletin`);
      const context = this.canvas.getContext('2d', {alpha: false});
      if (!context) throw new Error('Affichage non disponible.');
      const task = page.render({
        canvasContext: context,
        viewport,
        transform: [outputScale, 0, 0, outputScale, 0, 0],
        background: 'rgb(255,255,255)',
      });
      this.renderTask = task;
      this.renderDone = task.promise.catch(() => {});
      await task.promise;
      if (generation !== this.renderGeneration || document !== this.document) return;
      this.canvas.dataset.page = String(pageNumber);
      this.canvas.classList.remove('hidden');
      this.viewport.dataset.state = 'ready';
      this.viewport.setAttribute('aria-busy', 'false');
      this.message('');
    } catch (error) {
      if (generation !== this.renderGeneration || document !== this.document || error.name === 'RenderingCancelledException') return;
      this.canvas.classList.add('hidden');
      this.viewport.dataset.state = 'error';
      this.viewport.setAttribute('aria-busy', 'false');
      this.message('Cette page n’a pas pu être affichée. Réessayez ou sélectionnez une autre page.', true);
    } finally {
      if (generation === this.renderGeneration) this.renderTask = null;
      if (page) page.cleanup();
    }
  }

  close() {
    this.loadGeneration += 1;
    this.renderGeneration += 1;
    clearTimeout(this.resizeTimer);
    if (this.renderTask) this.renderTask.cancel();
    this.renderTask = null;
    const task = this.loadingTask;
    this.loadingTask = null;
    this.document = null;
    if (task) task.destroy().catch(() => {});
    this.newTab.removeAttribute('href');
    this.canvas.width = this.canvas.height = 0;
    this.canvas.classList.add('hidden');
    delete this.canvas.dataset.page;
    this.viewport.dataset.state = 'closed';
    this.viewport.setAttribute('aria-busy', 'false');
    this.pageNumber = 1;
    this.zoom = 1;
    this.zoomInput.value = '1';
    this.controls();
    this.message('');
  }
}
