// Point d'entrée principal du client.

import { get as getState, set as setState, subscribe } from './services/app_state.js';
import { loadPatients, refreshPatients } from './services/patients.js';
import { jsonGet, API_BASE } from './services/api.js';
import { initNewPatientModal } from './components/new_patient_modal.js';
import { initDiagnosticsPanel, updateDiagnosticsContext } from './components/diagnostics_panel.js';
import { initHeader } from './components/header.js';
import { ASSET_VERSION, withAssetVersion } from './services/assets.js';
import { listTabs, isValidTab, getTabEntry } from './services/tabs_registry.js';
import { safeDynamicImport } from './services/module_loader.js';

const REGISTERED_TABS = Object.freeze(listTabs());
const TAB_IDS = REGISTERED_TABS.map((tab) => tab.id);

const CARD_METRIC_MESSAGES = {
  pre_session(patient, count) {
    if (patient) {
      return `Briefing de ${patient.displayName}`;
    }
    return count > 0 ? 'Briefing en attente' : 'En attente de patients';
  },
  post_session(patient, count) {
    if (patient) {
      return `Compte rendu de ${patient.displayName}`;
    }
    return count > 0 ? 'Compte rendu en attente' : 'En attente de patients';
  },
  journal_critique(patient, count) {
    if (patient) {
      return `Journal critique de ${patient.displayName}`;
    }
    return count > 0 ? 'Journal à composer' : 'En attente de patients';
  },
  documents_aide(patient, count) {
    if (patient) {
      return `Documents pour ${patient.displayName}`;
    }
    return count > 0 ? 'Supports à préparer' : 'En attente de patients';
  },
  library(_patient, count) {
    return count > 0 ? 'Bibliothèque prête' : 'Initialisation requise';
  },
  constellation(patient, count) {
    if (patient) {
      return `Vue globale de ${patient.displayName}`;
    }
    return count > 0 ? 'Constellation à ouvrir' : 'En attente de patients';
  },
  anatomie3d() {
    return 'Exploration anatomique disponible';
  },
  facturation(patient, count) {
    if (patient) {
      return `Facturation de ${patient.displayName}`;
    }
    return count > 0 ? 'Facturation en attente' : 'En attente de patients';
  },
  agenda(patient, count) {
    if (patient) {
      return `Agenda de ${patient.displayName}`;
    }
    return count > 0 ? 'Agenda à planifier' : 'En attente de patients';
  },
  budget(patient, count) {
    if (patient) {
      return `Budget de ${patient.displayName}`;
    }
    return count > 0 ? 'Budget à estimer' : 'En attente de patients';
  },
};

const Modules = {};
let tabSwitchToken = 0;
let headerController = null;
window.Modules = Modules;

const TAB_ERROR_TITLES = {
  library: 'Module bibliothèque indisponible',
  anatomie3d: 'Chargement du modèle impossible',
};

function getTabContainer(tabId) {
  const tabRoot = document.querySelector('[data-tab-root]');
  if (!tabRoot) {
    return null;
  }
  return tabRoot.querySelector(`section[data-tab="${tabId}"]`);
}

function formatTabErrorMessage(error) {
  if (!error) {
    return 'Erreur inconnue.';
  }
  if (typeof error === 'string') {
    return error;
  }
  if (error instanceof Error) {
    return error.message || error.toString();
  }
  if (typeof error === 'object' && 'message' in error) {
    return String(error.message);
  }
  try {
    return JSON.stringify(error);
  } catch (_err) {
    return String(error);
  }
}

function clearTabError(tabId) {
  const container = getTabContainer(tabId);
  if (!container) {
    return;
  }
  delete container.dataset.tabError;
  const status = container.querySelector('[data-tab-status]');
  if (status) {
    status.remove();
  }
}

function renderTabError(tabId, options = {}) {
  const container = getTabContainer(tabId);
  if (!container) {
    return;
  }
  const {
    title = TAB_ERROR_TITLES[tabId] || 'Module indisponible',
    description = 'Une erreur est survenue lors du chargement de ce module.',
    retry = true,
    retryLabel = 'Réessayer',
    error,
  } = options;

  const detail = `${description}${error ? `\nDétails : ${formatTabErrorMessage(error)}` : ''}`;

  container.innerHTML = `
    <div class="tab-error" role="alert" data-tab-status>
      <h3>${title}</h3>
      <p class="tab-error__detail">${detail.replace(/\n/g, '<br>')}</p>
      ${
        retry
          ? `<button type="button" class="primary" data-action="retry-tab" data-tab-id="${tabId}">${retryLabel}</button>`
          : ''
      }
    </div>
  `;
  container.dataset.tabError = 'true';
  if (retry) {
    const button = container.querySelector('[data-action="retry-tab"]');
    if (button) {
      button.addEventListener(
        'click',
        () => {
          button.disabled = true;
          button.textContent = 'Nouvelle tentative…';
          void requestTabReload(tabId);
        },
        { once: true },
      );
    }
  }
}

async function requestTabReload(tabId) {
  if (!isValidTab(tabId)) {
    return;
  }
  const isActive = getState('activeTab') === tabId;
  const container = getTabContainer(tabId);
  if (container) {
    container.innerHTML = `
      <div class="tab-status" data-tab-status>
        <p>Rechargement du module…</p>
      </div>
    `;
  }
  const mod = await loadTabModule(tabId, { forceReload: true });
  if (!mod) {
    return;
  }
  if (isActive && typeof mod.show === 'function') {
    try {
      await mod.show();
    } catch (error) {
      logError(`[tab:${tabId}] show() failed after retry`, error);
      renderTabError(tabId, {
        description: 'Le module a échoué à l’affichage après réessai.',
        error,
      });
    }
  }
}

function navigate(target, options = {}) {
  const destination = typeof target === 'string' ? target : null;
  if (!destination || destination === 'home') {
    return showTab(null, { updateHash: options.updateHash ?? true });
  }
  if (isValidTab(destination)) {
    return showTab(destination, { updateHash: options.updateHash ?? true });
  }
  return Promise.resolve();
}

window.navigate = navigate;
window.requestTabReload = requestTabReload;
window.retryTab = requestTabReload;

function ensureTabContainers() {
  const root = document.querySelector('[data-tab-root]');
  if (!root) {
    return;
  }
  if (root.dataset.initialised === 'true') {
    return;
  }
  TAB_IDS.forEach((tab) => {
    const section = document.createElement('section');
    section.dataset.tab = tab;
    section.className = 'tab-section hidden';
    root.appendChild(section);
  });
  root.dataset.initialised = 'true';
}

const THEME_KEY = 'ui.theme';

function log(...args) {
  console.log('[assist-cli]', ...args);
}

function logError(...args) {
  console.error('[assist-cli]', ...args);
}

function showBanner(message, tone = 'error') {
  const banner = document.querySelector('[data-app-banner]');
  if (!banner) {
    return;
  }
  banner.textContent = message;
  banner.dataset.tone = tone;
  banner.hidden = false;
}

function clearBanner() {
  const banner = document.querySelector('[data-app-banner]');
  if (banner) {
    banner.hidden = true;
    banner.textContent = '';
    banner.dataset.tone = '';
  }
}

const patientsEmptyState = {
  root: null,
  status: null,
  retryBtn: null,
  demoBtn: null,
};

function ensurePatientsEmptyState() {
  if (patientsEmptyState.root) {
    return patientsEmptyState.root;
  }
  const host = document.querySelector('.app-main');
  if (!host) {
    return null;
  }
  const section = document.createElement('section');
  section.className = 'patients-empty-state';
  section.innerHTML = `
    <div class="patients-empty-state__banner" role="alert">
      <strong>Patients indisponibles</strong>
      <p data-empty-detail>Impossible de charger les patients. Vérifiez votre connexion puis réessayez.</p>
    </div>
    <p class="patients-empty-state__hint">
      Vous pouvez relancer le chargement ou utiliser le jeu de démonstration pour explorer l'interface.
    </p>
    <p class="patients-empty-state__status" data-empty-status aria-live="polite"></p>
    <div class="patients-empty-state__actions">
      <button type="button" data-action="patients-retry" class="primary">Réessayer</button>
      <button type="button" data-action="patients-demo" class="ghost">Charger la démo</button>
    </div>
  `;
  host.insertAdjacentElement('afterbegin', section);
  patientsEmptyState.root = section;
  patientsEmptyState.status = section.querySelector('[data-empty-status]');
  patientsEmptyState.retryBtn = section.querySelector('[data-action="patients-retry"]');
  patientsEmptyState.demoBtn = section.querySelector('[data-action="patients-demo"]');
  if (patientsEmptyState.retryBtn) {
    patientsEmptyState.retryBtn.addEventListener('click', () => {
      setPatientsEmptyStateBusy(true, 'Nouvelle tentative…');
      void performPatientsLoad();
    });
  }
  if (patientsEmptyState.demoBtn) {
    patientsEmptyState.demoBtn.addEventListener('click', () => {
      setPatientsEmptyStateBusy(true, 'Chargement du dataset de démonstration…');
      void performPatientsLoad({ forceDemo: true });
    });
  }
  return section;
}

function clearPatientsEmptyState() {
  const root = patientsEmptyState.root;
  if (root && root.parentNode) {
    root.parentNode.removeChild(root);
  }
  patientsEmptyState.root = null;
  patientsEmptyState.status = null;
  patientsEmptyState.retryBtn = null;
  patientsEmptyState.demoBtn = null;
}

function setPatientsEmptyStateBusy(isBusy, message = '') {
  const { root, status } = patientsEmptyState;
  if (!root) {
    return;
  }
  root.dataset.loading = isBusy ? 'true' : 'false';
  root.querySelectorAll('button').forEach((button) => {
    button.disabled = isBusy;
  });
  if (status) {
    status.textContent = message;
  }
}

function describePatientsError(error) {
  if (!error) {
    return 'Impossible de charger les patients.';
  }
  if (typeof error === 'string') {
    return error;
  }
  if (error.status) {
    return `Erreur ${error.status} lors du chargement des patients.`;
  }
  if (error.message) {
    return error.message;
  }
  return 'Un incident est survenu pendant le chargement des patients.';
}

function renderPatientsError(error) {
  const host = ensurePatientsEmptyState();
  if (!host) {
    return;
  }
  const detail = host.querySelector('[data-empty-detail]');
  if (detail) {
    detail.textContent = describePatientsError(error);
  }
  setPatientsEmptyStateBusy(false);
}

async function performPatientsLoad(options = {}) {
  if (patientsEmptyState.root) {
    setPatientsEmptyStateBusy(true, 'Chargement en cours…');
  }
  try {
    const result = await loadPatients(options);
    if (!result.list.length) {
      renderPatientsError(
        result.error ||
          'Aucun patient trouvé. Utilisez le bouton « Charger la démo » pour pré-remplir la liste.',
      );
    } else {
      clearPatientsEmptyState();
    }
    return result;
  } catch (error) {
    logError('patients load failed', error);
    renderPatientsError(error);
    return { list: [], source: null, error };
  } finally {
    setPatientsEmptyStateBusy(false);
  }
}

function getTabFromHash() {
  const hash = window.location.hash.slice(1);
  return isValidTab(hash) ? hash : null;
}

function getStoredTab() {
  try {
    const stored = localStorage.getItem('app:v1:lastTab');
    return isValidTab(stored) ? stored : null;
  } catch (error) {
    logError('localStorage error', error);
    return null;
  }
}

async function loadTabModule(tabId, options = {}) {
  const { forceReload = false } = options;
  if (!isValidTab(tabId)) {
    return null;
  }
  if (!forceReload && Modules[tabId]) {
    return Modules[tabId];
  }
  if (forceReload && Modules[tabId]) {
    const existing = Modules[tabId];
    if (existing && typeof existing.destroy === 'function') {
      try {
        existing.destroy();
      } catch (error) {
        logError(`[tab:${tabId}] destroy() failed`, error);
      }
    }
    delete Modules[tabId];
  }

  const entry = getTabEntry(tabId);
  if (!entry) {
    logError(`[tab:${tabId}] aucune entrée déclarée`);
    renderTabError(tabId, {
      title: 'Module introuvable',
      description: `Aucun point d’entrée n’est défini pour l’onglet « ${tabId} ».`,
      retry: false,
    });
    return null;
  }

  const moduleUrl = withAssetVersion(entry);
  const importDescription =
    tabId === 'library'
      ? 'Le module bibliothèque est indisponible pour le moment.'
      : 'Le module ne peut pas être chargé pour le moment.';
  const mod = await safeDynamicImport(moduleUrl, { cacheKey: tabId, forceReload });
  if (!mod) {
    logError(`[tab:${tabId}] import() a échoué`);
    renderTabError(tabId, {
      description: importDescription,
    });
    return null;
  }

  try {
    const initResult = typeof mod.init === 'function' ? mod.init() : null;
    if (initResult && typeof initResult.then === 'function') {
      await initResult;
    }
  } catch (error) {
    logError(`[tab:${tabId}] init() a échoué`, error);
    if (error && error.handled) {
      delete Modules[tabId];
      return null;
    }
    const initDescription =
      tabId === 'library'
        ? 'Le module bibliothèque n’a pas pu s’initialiser.'
        : 'L’initialisation du module a échoué.';
    renderTabError(tabId, {
      description: initDescription,
      error,
    });
    delete Modules[tabId];
    return null;
  }

  Modules[tabId] = mod;
  clearTabError(tabId);
  return mod;
}

async function showTab(tab, options = {}) {
  const next = isValidTab(tab) ? tab : null;
  const { updateHash = true } = options;
  const last = getState('activeTab');
  if (last === next) {
    return;
  }

  tabSwitchToken += 1;
  const requestToken = tabSwitchToken;

  const tabRoot = document.querySelector('[data-tab-root]');
  const hideSection = (tabId) => {
    if (!tabRoot || !tabId) {
      return;
    }
    const section = tabRoot.querySelector(`section[data-tab="${tabId}"]`);
    if (section) {
      section.classList.add('hidden');
    }
  };

  if (last) {
    hideSection(last);
    const lastModule = Modules[last];
    if (lastModule && typeof lastModule.hide === 'function') {
      try {
        lastModule.hide();
      } catch (error) {
        logError(`[tab:${last}] hide() failed`, error);
      }
    }
  }

  const intro = document.querySelector('.module-intro');
  const cards = document.querySelector('.module-cards');
  const hasActiveTab = Boolean(next);

  if (intro) {
    intro.classList.toggle('hidden', hasActiveTab);
  }
  if (cards) {
    cards.classList.toggle('hidden', hasActiveTab);
  }
  if (tabRoot) {
    if (hasActiveTab) {
      tabRoot.classList.add('is-active');
      tabRoot.querySelectorAll('section[data-tab]').forEach((section) => {
        const isCurrent = section.dataset.tab === next;
        section.classList.toggle('hidden', !isCurrent);
      });
    } else {
      tabRoot.classList.remove('is-active');
      tabRoot.querySelectorAll('section[data-tab]').forEach((section) => {
        section.classList.add('hidden');
      });
    }
  }

  document.body.dataset.activeTab = next || '';
  if (headerController && typeof headerController.setActiveTab === 'function') {
    headerController.setActiveTab(next);
  }
  setState('activeTab', next || null);

  try {
    if (next) {
      localStorage.setItem('app:v1:lastTab', next);
    } else {
      localStorage.removeItem('app:v1:lastTab');
    }
  } catch (error) {
    logError('localStorage error', error);
  }

  if (next) {
    const mod = await loadTabModule(next);
    if (tabSwitchToken !== requestToken) {
      return;
    }
    if (mod && typeof mod.show === 'function') {
      try {
        await mod.show();
      } catch (error) {
        if (error && error.handled) {
          logError(`[tab:${next}] show() handled error`, error);
        } else {
          logError(`[tab:${next}] show() failed`, error);
          renderTabError(next, {
            description: 'Le module a rencontré une erreur lors de son affichage.',
            error,
          });
        }
      }
    }
  }

  if (updateHash) {
    if (next) {
      const desiredHash = `#${next}`;
      if (window.location.hash !== desiredHash) {
        window.location.hash = next;
      }
    } else if (window.location.hash) {
      const url = `${window.location.pathname}${window.location.search}`;
      history.replaceState(null, '', url);
    }
  }
}

function handleHeaderNavigate(target) {
  if (target === 'home') {
    void showTab(null, { updateHash: true });
    return;
  }
  if (isValidTab(target)) {
    void showTab(target, { updateHash: true });
  }
}

function updateModuleCards() {
  const patients = getState('patientsCache') || [];
  const selectedId = getState('selectedPatientId');
  const selected = patients.find((patient) => patient.id === selectedId);
  const countLabel = patients.length ? `${patients.length} patient${patients.length > 1 ? 's' : ''}` : 'aucun patient';

  const selectedLabel = document.querySelector('[data-intro-selected]');
  if (selectedLabel) {
    selectedLabel.textContent = selected ? `Patient actuel : ${selected.displayName}` : 'Patient actuel : aucun';
  }
  const countLabelEl = document.querySelector('[data-intro-count]');
  if (countLabelEl) {
    countLabelEl.textContent = `Patients chargés : ${countLabel}`;
  }

  const totalPatients = patients.length;
  document.querySelectorAll('[data-card-metric]').forEach((metricEl) => {
    const key = metricEl.dataset.cardMetric;
    const formatter = CARD_METRIC_MESSAGES[key];
    let nextLabel;
    if (typeof formatter === 'function') {
      nextLabel = formatter(selected || null, totalPatients);
    }
    if (!nextLabel) {
      nextLabel = selected
        ? `Prêt pour ${selected.displayName}`
        : totalPatients > 0
        ? 'Sélectionnez un patient'
        : 'En attente de patients';
    }
    metricEl.textContent = nextLabel;
  });
}

async function verifyCriticalAssets() {
  try {
    const response = await jsonGet('/api/assets-manifest');
    const manifest = response?.assets || response?.data || {};
    const entries = Object.entries(manifest);
    if (!entries.length) {
      showBanner('Manifest des assets introuvable.', 'warning');
      return { ok: false, manifest: {} };
    }
    const problems = entries.filter(([, info]) => !info?.hash || info.size === '0');
    if (problems.length) {
      showBanner('Certains assets sont manquants ou vides.', 'warning');
      return { ok: false, manifest };
    }
    clearBanner();
    return { ok: true, manifest };
  } catch (error) {
    logError('manifest error', error);
    showBanner('Impossible de vérifier les assets critiques.', 'warning');
    return { ok: false, manifest: {} };
  }
}

function updateVersionIndicators(version) {
  const meta = document.querySelector('meta[data-app-version]');
  if (!meta) {
    return;
  }
  if (typeof version === 'string' && version) {
    meta.dataset.appVersion = version;
    meta.setAttribute('content', version);
  }
  const current = meta.dataset.appVersion || meta.getAttribute('content') || '';
  document.querySelectorAll('[data-app-version-label]').forEach((el) => {
    el.textContent = current || '—';
  });
}

function applyTheme(theme) {
  const root = document.documentElement;
  const desired = theme === 'dark' ? 'dark' : 'light';
  root.setAttribute('data-theme', desired);
  const themeBtn = document.getElementById('btnTheme') || headerController?.elements?.themeToggle;
  if (themeBtn) {
    themeBtn.setAttribute('aria-pressed', String(desired === 'dark'));
    themeBtn.textContent = desired === 'dark' ? '🌞' : '🌗';
    themeBtn.title = desired === 'dark' ? 'Passer en mode clair' : 'Passer en mode sombre';
    themeBtn.setAttribute(
      'aria-label',
      desired === 'dark' ? 'Passer en mode clair' : 'Passer en mode sombre',
    );
  }
}

function detectInitialTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'dark' || saved === 'light') {
      return saved;
    }
  } catch (_error) {
    // ignore storage issues
  }
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  return prefersDark ? 'dark' : 'light';
}

function initTheme() {
  applyTheme(detectInitialTheme());
  const btn = document.getElementById('btnTheme') || headerController?.elements?.themeToggle;
  if (btn && !btn.dataset.bound) {
    btn.dataset.bound = '1';
    btn.addEventListener('click', (event) => {
      event.preventDefault();
      const current = document.documentElement.getAttribute('data-theme') || 'light';
      const next = current === 'dark' ? 'light' : 'dark';
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch (_error) {
        // ignore storage failures
      }
      applyTheme(next);
    });
  }
}

function bindHeaderActions(controller) {
  const dashboardLink = document.querySelector('.brand[data-nav="home"]');
  if (dashboardLink) {
    dashboardLink.addEventListener('click', (event) => {
      event.preventDefault();
      void navigate('home');
    });
  }

  const refreshBtn =
    controller?.elements?.refreshPatients || document.querySelector('[data-action="refresh-patients"]');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async (event) => {
      event.preventDefault();
      const original = refreshBtn.textContent;
      refreshBtn.disabled = true;
      refreshBtn.textContent = 'Actualisation…';
      try {
        await refreshPatients();
      } catch (error) {
        console.error('[assist-cli] refresh patients failed', error);
        showBanner('Impossible de rafraîchir la liste des patients.', 'warning');
      } finally {
        refreshBtn.disabled = false;
        refreshBtn.textContent = original || 'Actualiser';
      }
    });
  }
}

async function initialise() {
  updateVersionIndicators(ASSET_VERSION);
  initDiagnosticsPanel({
    apiBase: API_BASE,
    onRequestDemo: () => performPatientsLoad({ forceDemo: true }),
    verifyAssets: verifyCriticalAssets,
  });

  initNewPatientModal();
  bindHeaderActions(headerController);

  try {
    const healthResponse = await jsonGet('/api/health');
    setState('demoMode', Boolean(healthResponse?.demo_mode));
    setState('serverPort', healthResponse?.port || null);
    updateDiagnosticsContext({ port: healthResponse?.port, demoMode: Boolean(healthResponse?.demo_mode) });
  } catch (error) {
    log('health endpoint unavailable', error);
  }

  try {
    const versionResponse = await jsonGet('/api/version');
    if (versionResponse?.assetVersion) {
      window.ASSET_VERSION = versionResponse.assetVersion;
      updateVersionIndicators(versionResponse.assetVersion);
    }
  } catch (error) {
    log('version endpoint unavailable', error);
  }

  await verifyCriticalAssets();

  const patientsResult = await performPatientsLoad();
  if (patientsResult.error) {
    showBanner('Impossible de charger les patients.', 'error');
  }

  subscribe('patientsCache', updateModuleCards);
  subscribe('selectedPatientId', updateModuleCards);
  updateModuleCards();

  const hashTab = getTabFromHash();
  const storedTab = hashTab ? null : getStoredTab();
  const initial = hashTab || (storedTab === 'agenda' ? null : storedTab);

  if (initial) {
    await showTab(initial, { updateHash: !hashTab });
  } else {
    await showTab(null, { updateHash: false });
  }

  window.addEventListener('hashchange', () => {
    const next = getTabFromHash();
    void showTab(next, { updateHash: false });
  });
}

function safeInitialise() {
  try {
    void initialise();
  } catch (error) {
    logError('initialisation impossible', error);
    showBanner('Initialisation interrompue. Consultez le panneau Diagnostic.', 'error');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const bannerHost = document.querySelector('.app-banner');
  if (bannerHost) {
    bannerHost.innerHTML = '<div class="banner" data-app-banner hidden aria-live="polite"></div>';
  }
  headerController = initHeader({
    tabs: TAB_IDS,
    onNavigate: handleHeaderNavigate,
  });
  initTheme();
  window.addEventListener(
    'load',
    () => {
      if (headerController && typeof headerController.refreshLayout === 'function') {
        headerController.refreshLayout();
      }
    },
    { once: true },
  );
  ensureTabContainers();
  window.addEventListener('patients:load-error', (event) => {
    renderPatientsError(event?.detail?.error);
  });
  window.addEventListener('assist:retry-tab', (event) => {
    const tabId = event?.detail?.tabId;
    if (isValidTab(tabId)) {
      void requestTabReload(tabId);
    }
  });
  safeInitialise();
});

