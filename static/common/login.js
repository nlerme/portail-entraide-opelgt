'use strict';

const form = document.querySelector('#loginForm');
const login = document.querySelector('#login');
const password = document.querySelector('#password');
const submit = document.querySelector('#submit');
const message = document.querySelector('#message');
const sessionDuration = document.querySelector('#sessionDuration');

function showError(text) {
  message.textContent = text;
  message.classList.toggle('hidden', !text);
}

function formatDuration(minutes) {
  const value = Math.max(1, Number(minutes) || 30);
  return `${value} minute${value > 1 ? 's' : ''}`;
}

async function requestJson(url, options = {}, timeout = 45000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {...options, signal: controller.signal, cache: 'no-store'});
    let payload = {};
    try { payload = await response.json(); } catch {}
    if (!response.ok) throw new Error(payload.message || payload.detail || `Erreur HTTP ${response.status}`);
    return payload;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Le serveur de connexion ne répond pas.');
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const user = login.value.trim();
  const secret = password.value;
  if (!user || !secret) {
    showError('Saisissez votre identifiant et votre mot de passe.');
    return;
  }
  showError('');
  submit.disabled = true;
  submit.textContent = 'Connexion en cours…';
  try {
    await requestJson('/api/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({login: user, password: secret}),
    });
    password.value = '';
    window.location.replace('/services');
  } catch (error) {
    password.value = '';
    showError(error.message);
    password.focus();
  } finally {
    submit.disabled = false;
    submit.textContent = 'Se connecter';
  }
});

window.PortalUI.startConnectivity();

(async () => {
  try {
    const session = await requestJson('/api/session', {}, 10000);
    sessionDuration.textContent = formatDuration(session.durationMinutes);
    if (session.authenticated) window.location.replace('/services');
  } catch {}
})();
