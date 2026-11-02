'use strict';

(() => {
  const link = document.querySelector('[data-login-qr]');
  if (!link) return;

  // The address belongs to this portal, with no credentials, query or session token.
  const target = new URL(link.dataset.loginQr, window.location.origin);
  link.href = target.href;
  link.title = target.href;
  const qr = qrcodegen.QrCode.encodeText(target.href, qrcodegen.QrCode.Ecc.MEDIUM);
  const border = 4;
  const size = qr.size + border * 2;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', link.getAttribute('aria-label'));
  svg.setAttribute('shape-rendering', 'crispEdges');
  const background = document.createElementNS(ns, 'rect');
  background.setAttribute('width', '100%');
  background.setAttribute('height', '100%');
  background.setAttribute('fill', '#fff');
  svg.appendChild(background);
  const path = document.createElementNS(ns, 'path');
  const cells = [];
  for (let y = 0; y < qr.size; y += 1) {
    for (let x = 0; x < qr.size; x += 1) {
      if (qr.getModule(x, y)) cells.push(`M${x + border},${y + border}h1v1h-1z`);
    }
  }
  path.setAttribute('d', cells.join(''));
  path.setAttribute('fill', '#000');
  svg.appendChild(path);
  link.replaceChildren(svg);
})();
