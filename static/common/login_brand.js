'use strict';

(() => {
  const link = document.querySelector('[data-login-qr]');
  if (!link) return;
  const target = new URL(link.dataset.loginQr, window.location.origin);
  link.href = target.href;
  link.title = `Agrandir le QR code — ${target.href}`;
  link.setAttribute('role', 'button');
  link.setAttribute('aria-haspopup', 'dialog');
  link.setAttribute('aria-label', `${link.getAttribute('aria-label')} ; cliquer pour agrandir`);
  const qr = qrcodegen.QrCode.encodeText(target.href, qrcodegen.QrCode.Ecc.MEDIUM);
  const modules = qr.size + 8;
  const ns = 'http://www.w3.org/2000/svg';
  const symbols = [];
  const observer = new ResizeObserver(schedule);
  let frame = 0;

  function addSymbol(parent) {
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `QR code vers ${target.href}`);
    svg.setAttribute('shape-rendering', 'crispEdges');
    const background = document.createElementNS(ns, 'rect');
    background.setAttribute('width', '100%');
    background.setAttribute('height', '100%');
    background.setAttribute('fill', '#fff');
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('fill', '#000');
    svg.append(background, path);
    parent.replaceChildren(svg);
    symbols.push({svg, path});
    observer.observe(parent);
  }

  function render({svg, path}) {
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const viewport = window.visualViewport;
    const ratio = (window.devicePixelRatio || 1) * (viewport?.scale || 1);
    const originX = (rect.left - (viewport?.offsetLeft || 0)) * ratio;
    const originY = (rect.top - (viewport?.offsetTop || 0)) * ratio;
    let width = rect.width * ratio;
    let height = rect.height * ratio;
    let cell = Math.floor(Math.min(width, height) / modules);
    let left;
    let top;
    if (cell < 1) {
      // Preserve the entire symbol at extreme zoom-out; enlargement remains available.
      width = height = modules;
      cell = 1;
      left = top = 0;
    } else {
      // Integer physical pixels avoid unequal module widths after a resize or zoom.
      left = Math.round(originX + (width - modules * cell) / 2) - originX;
      top = Math.round(originY + (height - modules * cell) / 2) - originY;
    }
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    const cells = [];
    for (let y = 0; y < qr.size; y += 1) {
      for (let x = 0; x < qr.size; x += 1) {
        if (qr.getModule(x, y)) cells.push(`M${left + (x + 4) * cell},${top + (y + 4) * cell}h${cell}v${cell}h-${cell}z`);
      }
    }
    path.setAttribute('d', cells.join(''));
  }

  function schedule() {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      symbols.forEach(render);
    });
  }

  addSymbol(link);
  const dialog = document.createElement('dialog');
  dialog.className = 'login-qr-dialog';
  dialog.setAttribute('aria-label', 'QR code de la page de connexion');
  const title = document.createElement('h2');
  title.textContent = target.pathname === '/admin' ? 'Connexion administrateur' : 'Connexion membre';
  const large = document.createElement('div');
  large.className = 'login-qr-large';
  addSymbol(large);
  const address = document.createElement('p');
  address.className = 'login-qr-address';
  address.textContent = target.href;
  const close = document.createElement('button');
  close.type = 'button';
  close.textContent = 'Fermer';
  close.addEventListener('click', () => dialog.close());
  dialog.append(title, large, address, close);
  document.body.append(dialog);
  link.addEventListener('click', event => {
    event.preventDefault();
    if (!dialog.open) dialog.showModal();
    close.focus();
    schedule();
  });
  link.addEventListener('keydown', event => {
    if (event.key === ' ') { event.preventDefault(); link.click(); }
  });
  window.addEventListener('resize', schedule);
  window.visualViewport?.addEventListener('resize', schedule);
  window.visualViewport?.addEventListener('scroll', schedule);
  let resolution;
  function watchResolution() {
    resolution?.removeEventListener('change', watchResolution);
    resolution = matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
    resolution.addEventListener('change', watchResolution, {once:true});
    schedule();
  }
  watchResolution();
})();
