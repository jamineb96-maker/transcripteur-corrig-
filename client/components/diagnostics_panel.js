import { get as getState, subscribe } from '../services/app_state.js';
import { jsonPost } from '../services/api.js';

const STORAGE_KEY = 'app:v1:diagCollapsed';

let container;
let collapsed = true;
let triggerButtons = [];
let apiBaseUrl = '';
let optionsCache = {};
let pending = false;

function setCollapsed(next, { persist = true } = {}) {
  collapsed = Boolean(next);
  document.body.classList.toggle('diag-collapsed', collapsed);
  if (container) {
    container.setAttribute('aria-hidden', collapsed ? 'true' : 'false');
  }
  triggerButtons.forEach((button) => {
    button.setAttribute('aria-pressed', collapsed ? 'false' : 'true');
  });
  if (persist) {
    try {
      localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
    } catch (_error) {
      /* ignore */
    }
  }
  if (!collapsed) {
    refreshPanel();
  }
}

function consumeDiagnosticsQuery() {
  if (typeof window === 'undefined') {
    return false;
  }
  const { search, hash, pathname } = window.location;
  if (!search) {
    return false;
  }
  const params = new URLSearchParams(search);
  if (!params.has('diag')) {
    return false;
  }
  params.delete('diag');
  const nextSearch = params.toString();
  const nextUrl = `${pathname}${nextSearch ? `?${nextSearch}` : ''}${hash || ''}`;
  const hasHistoryReplace = window.history && typeof window.history.replaceState === 'function';
  if (hasHistoryReplace) {
    const current = `${pathname}${search}${hash || ''}`;
    if (nextUrl !== current) {
      try {
        const state = window.history.state;
        window.history.replaceState(state, document.title, nextUrl);
      } catch (_error) {
        // ignore history errors
      }
    }
  }
  return true;
}

function ensureStructure() {
  if (!container) {
    return;
  }
  container.innerHTML = `
    <div class="diagnostics__header">
      <div>
        <h3>Diagnostic</h3>
        <p class="diagnostics__subtitle">Suivi du serveur et des données locales</p>
      </div>
      <div class="diagnostics__actions">
        <button type="button" class="diagnostics__action" data-role="refresh">Actualiser</button>
        <button type="button" class="diagnostics__action" data-role="rescan">Rescanner</button>
        <button type="button" class="diagnostics__action" data-role="request-demo">Charger la démo</button>
      </div>
    </div>
    <div class="diagnostics__meta-grid">
      <span data-diag-field="api-base">API : ${apiBaseUrl || 'relative /'}</span>
      <span data-diag-field="cors">Origine : ${window.location.origin}</span>
      <span data-diag-field="port">Port serveur : —</span>
      <span data-diag-field="demo">Mode démo : inconnu</span>
    </div>
    <section class="diagnostics__patients" data-role="patients">
      <header>
        <strong>Patients — <span data-diag-field="patients-source">source inconnue</span></strong>
        <span data-diag-field="patients-count"></span>
      </header>
      <ul data-diag-field="patients-roots" class="diagnostics__roots"></ul>
    </section>
    <ul class="diagnostics__list" data-role="list"></ul>
    <div class="diagnostics__footer">
      <button type="button" class="ghost" data-role="sw-status">Analyser les Service Workers</button>
      <span data-diag-field="sw">SW : en attente…</span>
    </div>
  `;
}

function updatePortInfo(port, demoMode) {
  if (!container) {
    return;
  }
  const portLabel = container.querySelector('[data-diag-field="port"]');
  const demoLabel = container.querySelector('[data-diag-field="demo"]');
  if (portLabel) {
    portLabel.textContent = `Port serveur : ${port || '—'}`;
  }
  if (demoLabel) {
    demoLabel.textContent = `Mode démo : ${demoMode ? 'actif' : 'désactivé'}`;
  }
}

function updatePatientsSummary({ source, count, roots }) {
  if (!container) {
    return;
  }
  const sourceEl = container.querySelector('[data-diag-field="patients-source"]');
  const countEl = container.querySelector('[data-diag-field="patients-count"]');
  const rootsEl = container.querySelector('[data-diag-field="patients-roots"]');
  if (sourceEl) {
    sourceEl.textContent = `Source : ${source || 'inconnue'}`;
  }
  if (countEl) {
    countEl.textContent = `${count || 0} patient${count === 1 ? '' : 's'}`;
  }
  if (rootsEl) {
    rootsEl.innerHTML = '';
    if (roots && roots.length) {
      roots.forEach((rootPath) => {
        const li = document.createElement('li');
        li.textContent = rootPath;
        rootsEl.appendChild(li);
      });
    } else {
      const li = document.createElement('li');
      li.textContent = 'Aucune racine détectée';
      rootsEl.appendChild(li);
    }
  }
}

async function detectServiceWorkers() {
  if (!('serviceWorker' in navigator)) {
    return { active: false, registrations: [] };
  }
  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    return { active: registrations.length > 0, registrations };
  } catch (_error) {
    return { active: false, registrations: [] };
  }
}

function buildResultItem(result) {
  const li = document.createElement('li');
  li.className = `diagnostics__item diagnostics__item--${result.status}`;
  li.innerHTML = `
    <span class="diagnostics__badge" aria-hidden="true"></span>
    <div class="diagnostics__details">
      <span class="diagnostics__label">${result.label}</span>
      <span class="diagnostics__meta">${result.message}</span>
      ${result.extra ? `<small class="diagnostics__extra">${result.extra}</small>` : ''}
    </div>
    <code class="diagnostics__endpoint">${result.url}</code>
  `;
  return li;
}

async function safeFetchJson(url) {
  const started = performance.now();
  const response = await fetch(url, { cache: 'no-store' });
  const latency = performance.now() - started;
  let body = null;
  try {
    body = await response.json();
  } catch (_error) {
    body = null;
  }
  return { response, latency, body };
}

function formatLatency(latency) {
  if (typeof latency !== 'number' || Number.isNaN(latency)) {
    return 'n/d';
  }
  return `${latency.toFixed(0)} ms`;
}

async function checkEndpoint(endpoint) {
  const url = apiBaseUrl ? `${apiBaseUrl}${endpoint.url}` : endpoint.url;
  try {
    const { response, latency, body } = await safeFetchJson(url);
    if (!response.ok) {
      return {
        key: endpoint.key,
        label: endpoint.label,
        url,
        status: 'error',
        message: `${response.status} ${response.statusText || ''}`.trim() || 'Erreur',
        extra: `Latence ${formatLatency(latency)}`,
        payload: body,
      };
    }
    let message = `OK — ${formatLatency(latency)}`;
    let extra = '';
    let status = 'ok';
    if (endpoint.key === 'patients' && body) {
      const count = Array.isArray(body.items) ? body.items.length : body.count || 0;
      const source = body.source || 'inconnu';
      const roots = Array.isArray(body.roots) ? body.roots : [];
      message = `${count} patient${count === 1 ? '' : 's'} — ${formatLatency(latency)}`;
      extra = `Source : ${source}`;
      updatePatientsSummary({ source, count, roots });
    }
    if (endpoint.key === 'health' && body) {
      extra = `Static OK : ${body.static_ok ? 'oui' : 'non'} • Source patients : ${body.patients_source}`;
    }
    if (endpoint.key === 'patients-fs' && body) {
      const kept = Number.isFinite(Number(body.kept)) ? Number(body.kept) : Number(body.count) || 0;
      const hasTotal = Number.isFinite(Number(body.total_entries));
      const total = hasTotal ? Number(body.total_entries) : kept;
      const apiCount = Number.isFinite(Number(body.count)) ? Number(body.count) : kept;
      const dir = typeof body.dir_abs === 'string' ? body.dir_abs : '';
      const samples = Array.isArray(body.sample) ? body.sample.slice(0, 3) : [];
      const mismatch = kept !== apiCount;
      status = mismatch ? 'warning' : 'ok';
      message = `${kept} dossier${kept === 1 ? '' : 's'} valides / ${apiCount} API`;
      extra = [
        mismatch ? 'Écart avec /api/patients' : 'Synchronisé',
        dir ? `Dossier : ${dir}` : '',
        hasTotal ? `Entrées FS : ${total}` : '',
        samples.length ? `Échantillon : ${samples.join(', ')}` : '',
      ]
        .filter(Boolean)
        .join(' • ');
    }

    return {
      key: endpoint.key,
      label: endpoint.label,
      url,
      status,
      message,
      extra,
      payload: body,
    };
  } catch (error) {
    return {
      key: endpoint.key,
      label: endpoint.label,
      url,
      status: 'error',
      message: error instanceof Error ? error.message : String(error),
      extra: '',
      payload: null,
    };
  }
}

const ENDPOINTS = [
  { key: 'health', label: "Santé de l'API", url: '/api/health' },
  { key: 'patients', label: 'Patients', url: '/api/patients' },
  { key: 'patients-fs', label: 'Patients — FS', url: '/api/patients/diagnostics' },
  { key: 'budget-presets', label: 'Budget — Presets', url: '/api/budget/presets' },
  { key: 'budget-history', label: 'Budget — Historique démo', url: '/api/budget/history?patient=demo' },
];

async function refreshPanel() {
  if (!container || pending) {
    return;
  }
  pending = true;
  const listEl = container.querySelector('[data-role="list"]');
  if (listEl) {
    listEl.innerHTML = '<li class="diagnostics__item diagnostics__item--loading">Chargement…</li>';
  }
  const results = [];
  for (const endpoint of ENDPOINTS) {
    // eslint-disable-next-line no-await-in-loop
    const result = await checkEndpoint(endpoint);
    results.push(result);
  }
  if (optionsCache.verifyAssets) {
    try {
      // eslint-disable-next-line no-await-in-loop
      const assets = await optionsCache.verifyAssets();
      results.push({
        key: 'assets',
        label: 'Assets critiques',
        url: 'client assets',
        status: assets?.ok ? 'ok' : 'warning',
        message: assets?.ok ? 'Manifest complet' : 'Vérifier les assets critiques',
        extra: '',
      });
    } catch (error) {
      results.push({
        key: 'assets',
        label: 'Assets critiques',
        url: 'client assets',
        status: 'error',
        message: error instanceof Error ? error.message : String(error),
        extra: '',
      });
    }
  }

  if (listEl) {
    listEl.innerHTML = '';
    results.forEach((result) => {
      listEl.appendChild(buildResultItem(result));
    });
  }
  pending = false;
}

async function rescanPatients() {
  if (!container) {
    return;
  }
  const button = container.querySelector('[data-role="rescan"]');
  if (button) {
    button.disabled = true;
    button.textContent = 'Rescan…';
  }
  try {
    const response = await jsonPost('/api/patients/refresh', {});
    const source = response?.source || 'archives';
    const roots = Array.isArray(response?.roots) ? response.roots : [];
    const count = Array.isArray(response?.items) ? response.items.length : response?.count || 0;
    updatePatientsSummary({ source, count, roots });
  } catch (error) {
    console.error('[assist-cli] rescan failed', error);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = 'Rescanner';
    }
  }
}

async function inspectServiceWorkers() {
  const info = await detectServiceWorkers();
  if (!container) {
    return;
  }
  const target = container.querySelector('[data-diag-field="sw"]');
  if (target) {
    target.textContent = info.active
      ? `SW actifs (${info.registrations.length})`
      : 'SW inactifs';
  }
}

function bindInteractions() {
  if (!container) {
    return;
  }
  container.addEventListener('click', (event) => {
    const action = event.target?.dataset?.role;
    if (!action) {
      return;
    }
    switch (action) {
      case 'refresh':
        refreshPanel();
        break;
      case 'rescan':
        rescanPatients();
        break;
      case 'request-demo':
        if (typeof optionsCache.onRequestDemo === 'function') {
          optionsCache.onRequestDemo();
        }
        break;
      case 'sw-status':
        inspectServiceWorkers();
        break;
      default:
        break;
    }
  });
}

function registerTrigger(button) {
  if (!button) {
    return;
  }
  if (!triggerButtons.includes(button)) {
    triggerButtons.push(button);
    button.addEventListener('click', (event) => {
      event.preventDefault();
      const diag = typeof window !== 'undefined' ? window.__diag : null;
      if (diag && typeof diag.show === 'function' && typeof diag.hide === 'function') {
        if (collapsed) {
          diag.show();
        } else {
          diag.hide();
        }
      } else {
        setCollapsed(!collapsed);
      }
    });
  }
  button.setAttribute('aria-pressed', collapsed ? 'false' : 'true');
}

export function initDiagnosticsPanel(options = {}) {
  optionsCache = options;
  apiBaseUrl = options.apiBase || '';
  container = document.querySelector('[data-component="diagnostics"]');
  if (typeof window !== 'undefined') {
    window.__diag = {
      show: () => setCollapsed(false),
      hide: () => setCollapsed(true),
    };
  }
  if (!container) {
    return;
  }
  ensureStructure();
  bindInteractions();

  document.querySelectorAll('[data-action="toggle-diagnostics"]').forEach((button) => {
    registerTrigger(button);
  });

  let stored = null;
  try {
    stored = localStorage.getItem(STORAGE_KEY);
  } catch (_error) {
    stored = null;
  }

  const shouldForceOpen = consumeDiagnosticsQuery();

  if (shouldForceOpen) {
    setCollapsed(false);
  } else if (stored === '0') {
    setCollapsed(false, { persist: false });
  } else {
    setCollapsed(true, { persist: false });
  }

  subscribe('patientsCache', (list) => {
    const patients = Array.isArray(list) ? list : [];
    const source = getState('patientsSource') || 'inconnu';
    const roots = getState('patientsRoots') || [];
    updatePatientsSummary({ source, count: patients.length, roots });
  });
  subscribe('patientsRoots', (roots) => {
    const patients = getState('patientsCache') || [];
    const source = getState('patientsSource') || 'inconnu';
    updatePatientsSummary({ source, count: patients.length, roots: Array.isArray(roots) ? roots : [] });
  });
  subscribe('patientsSource', (source) => {
    const patients = getState('patientsCache') || [];
    const roots = getState('patientsRoots') || [];
    updatePatientsSummary({ source, count: patients.length, roots });
  });

  const initialPatients = getState('patientsCache') || [];
  const initialSource = getState('patientsSource') || 'inconnu';
  const initialRoots = getState('patientsRoots') || [];
  updatePatientsSummary({ source: initialSource, count: initialPatients.length, roots: initialRoots });

  if (!collapsed) {
    refreshPanel();
  }
}

export function updateDiagnosticsContext({ port, demoMode } = {}) {
  updatePortInfo(port, demoMode);
}

export { refreshPanel };
