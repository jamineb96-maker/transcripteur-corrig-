// # [pipeline-v3 begin]
import { subscribe as subscribeState } from '../../services/app_state.js';
import { jsonPost } from '../../services/api.js';

const FEATURES = window.APP_FEATURES || {};
const LIBRARY_AUTOSUGGEST = Boolean(FEATURES.library_autosuggest);

const STORAGE_KEYS = {
  mail: 'presession:raw:mail',
  etat: 'presession:raw:etat',
  notes: 'presession:raw:notes',
  plan: 'presession:plan',
  researchLocal: 'presession:research:local',
  researchWeb: 'presession:research:web',
  researchNotes: 'presession:research:notes',
  researchLibrary: 'presession:research:library',
  prompt: 'presession:prompt',
};

let container;
let initialized = false;
let unsubscribePatient = null;

const state = {
  rawContext: null,
  plan: null,
  previousPlan: null,
  research: null,
  libraryResults: [],
  prompt: '',
};

const refs = {
  mail: null,
  etat: null,
  notes: null,
  planButton: null,
  researchButton: null,
  promptButton: null,
  copyButton: null,
  exportButton: null,
  allowInternet: null,
  alertPlan: null,
  alertResearch: null,
  alertPrompt: null,
  planDiff: null,
  researchLocal: null,
  researchLibrary: null,
  researchWeb: null,
  researchNotes: null,
  libraryToggle: null,
  promptArea: null,
  planForm: {
    orientation: null,
    objectif: null,
    cadre: null,
    situation: null,
    tensions: null,
    axes: null,
    cloture: null,
  },
};

function ensureStyle() {
  const href = `/static/tabs/pre_session/style.css?v=${window.ASSET_VERSION || ''}`;
  if (!document.querySelector(`link[href="${href}"]`)) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }
}

function ensureTriadIntegrity() {
  const buttons = [refs.planButton, refs.researchButton, refs.promptButton];
  const hasAll = buttons.every((btn) => btn instanceof HTMLElement);
  if (!hasAll) {
    console.error('Pré-séance : triade de boutons incomplète, opération bloquée.');
    buttons.forEach((btn) => {
      if (btn) {
        btn.disabled = true;
      }
    });
    return;
  }
  const unique = new Set(buttons);
  if (unique.size !== buttons.length) {
    throw new Error('Interface invalide : fusion de boutons détectée.');
  }
}

function mapRefs() {
  if (!container) {
    return;
  }
  refs.mail = container.querySelector('#ps-mail-brut');
  refs.etat = container.querySelector('#ps-etat');
  refs.notes = container.querySelector('#ps-notes');
  refs.planButton = container.querySelector('#ps-btn-plan');
  refs.researchButton = container.querySelector('#ps-btn-research');
  refs.promptButton = container.querySelector('#ps-btn-prompt');
  refs.copyButton = container.querySelector('#ps-btn-copy');
  refs.exportButton = container.querySelector('#ps-btn-export');
  refs.allowInternet = container.querySelector('#ps-allow-internet');
  refs.libraryToggle = container.querySelector('#ps-library-toggle');
  refs.alertPlan = container.querySelector('[data-role="plan-alert"]');
  refs.alertResearch = container.querySelector('[data-role="research-alert"]');
  refs.alertPrompt = container.querySelector('[data-role="prompt-alert"]');
  refs.planDiff = container.querySelector('#ps-plan-diff');
  refs.researchLocal = container.querySelector('#ps-research-local');
  refs.researchLibrary = container.querySelector('#ps-research-library');
  refs.researchWeb = container.querySelector('#ps-research-web');
  refs.researchNotes = container.querySelector('#ps-research-notes');
  refs.promptArea = container.querySelector('#ps-prompt-final');
  refs.planForm.orientation = container.querySelector('#ps-plan-orientation');
  refs.planForm.objectif = container.querySelector('#ps-plan-objectif');
  refs.planForm.cadre = container.querySelector('#ps-plan-cadre');
  refs.planForm.situation = container.querySelector('#ps-plan-situation');
  refs.planForm.tensions = container.querySelector('#ps-plan-tensions');
  refs.planForm.axes = container.querySelector('#ps-plan-axes');
  refs.planForm.cloture = container.querySelector('#ps-plan-cloture');
  ensureTriadIntegrity();

  if (refs.researchLibrary && !LIBRARY_AUTOSUGGEST) {
    const field = refs.researchLibrary.closest('[data-library-field]');
    if (field) field.setAttribute('hidden', 'hidden');
  }
  if (refs.libraryToggle) {
    if (!LIBRARY_AUTOSUGGEST) {
      const toggleWrapper = refs.libraryToggle.closest('[data-library-toggle]');
      if (toggleWrapper) toggleWrapper.setAttribute('hidden', 'hidden');
    } else {
      refs.libraryToggle.checked = true;
    }
  }
}

function setAlert(target, message = '', tone = 'error') {
  const ref = refs[target];
  if (!ref) {
    return;
  }
  if (!message) {
    ref.hidden = true;
    ref.textContent = '';
    ref.dataset.tone = '';
    return;
  }
  ref.hidden = false;
  ref.textContent = message;
  ref.dataset.tone = tone;
}

function collectRawContext() {
  return {
    mail_brut: (refs.mail?.value || '').trim(),
    etat_depuis_derniere: (refs.etat?.value || '').trim(),
    notes_therapeutiques: (refs.notes?.value || '').trim(),
  };
}

function persistRawContext() {
  const raw = collectRawContext();
  try {
    localStorage.setItem(STORAGE_KEYS.mail, raw.mail_brut || '');
    localStorage.setItem(STORAGE_KEYS.etat, raw.etat_depuis_derniere || '');
    localStorage.setItem(STORAGE_KEYS.notes, raw.notes_therapeutiques || '');
  } catch (error) {
    console.warn('Impossible de persister le matériau brut', error);
  }
}

function collectPlanFromForm() {
  return {
    orientation: refs.planForm.orientation?.value.trim() || '',
    objectif_prioritaire: refs.planForm.objectif?.value.trim() || '',
    cadre_de_travail: refs.planForm.cadre?.value.trim() || '',
    synthese: {
      situation_actuelle: refs.planForm.situation?.value.trim() || '',
      tensions_principales: refs.planForm.tensions?.value.trim() || '',
      axes_de_travail: refs.planForm.axes?.value.trim() || '',
    },
    cloture_attendue: refs.planForm.cloture?.value.trim() || '',
    diff_avec_plan_precedent: state.plan?.diff_avec_plan_precedent || {
      orientation_modifiee: false,
      elements_ajoutes: [],
      elements_retires: [],
    },
  };
}

function fillPlanForm(plan) {
  if (!plan) {
    ['orientation', 'objectif', 'cadre', 'situation', 'tensions', 'axes', 'cloture'].forEach((key) => {
      const field = refs.planForm[key];
      if (field) {
        field.value = '';
      }
    });
    return;
  }
  if (refs.planForm.orientation) refs.planForm.orientation.value = plan.orientation || '';
  if (refs.planForm.objectif) refs.planForm.objectif.value = plan.objectif_prioritaire || '';
  if (refs.planForm.cadre) refs.planForm.cadre.value = plan.cadre_de_travail || '';
  if (refs.planForm.situation) refs.planForm.situation.value = plan.synthese?.situation_actuelle || '';
  if (refs.planForm.tensions) refs.planForm.tensions.value = plan.synthese?.tensions_principales || '';
  if (refs.planForm.axes) refs.planForm.axes.value = plan.synthese?.axes_de_travail || '';
  if (refs.planForm.cloture) refs.planForm.cloture.value = plan.cloture_attendue || '';
}

function formatDiff(diff) {
  if (!diff) {
    return 'Aucune donnée précédente.';
  }
  const lines = [];
  if (diff.orientation_modifiee) {
    lines.push('Orientation modifiée.');
  }
  if (diff.elements_ajoutes && diff.elements_ajoutes.length) {
    lines.push('Ajouts :');
    diff.elements_ajoutes.forEach((item) => lines.push(`• ${item}`));
  }
  if (diff.elements_retires && diff.elements_retires.length) {
    lines.push('Retraits :');
    diff.elements_retires.forEach((item) => lines.push(`• ${item}`));
  }
  if (!lines.length) {
    lines.push('Pas de différence majeure.');
  }
  return lines.join('\n');
}

function updateDiff(diff) {
  if (refs.planDiff) {
    refs.planDiff.textContent = formatDiff(diff);
  }
}

function updateButtons({ busy = false } = {}) {
  const raw = collectRawContext();
  const hasMail = Boolean(raw.mail_brut);
  const hasPlan = Boolean(state.plan);
  const hasResearch = Boolean(state.research);
  if (refs.planButton) {
    refs.planButton.disabled = busy || !hasMail;
  }
  if (refs.researchButton) {
    refs.researchButton.disabled = busy || !hasPlan;
  }
  if (refs.promptButton) {
    refs.promptButton.disabled = busy || !hasPlan || !hasResearch;
  }
  if (refs.copyButton) {
    refs.copyButton.disabled = !state.prompt;
  }
  if (refs.exportButton) {
    refs.exportButton.disabled = !state.prompt;
  }
}

function serializeResearchList(items, formatter) {
  if (!items || !items.length) {
    return '';
  }
  return items
    .map((item) => formatter(item))
    .filter(Boolean)
    .join('\n\n');
}

function formatWebResearchItem(item) {
  if (!item) {
    return '';
  }
  const clean = (value) => {
    if (typeof value !== 'string') {
      return '';
    }
    return value.replace(/https?:\/\//gi, '').trim();
  };
  const snippet = clean(item.snippet || item.resume || '');
  const candidates = [item.title, item.source_note, item.url, item.site]
    .map((value) => clean(value))
    .filter(Boolean);
  const seen = new Set();
  const details = candidates.filter((value) => {
    const key = value.toLowerCase();
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
  if (!snippet && !details.length) {
    return '';
  }
  if (!details.length) {
    return snippet;
  }
  const meta = details.join(' — ');
  return [snippet, `Source : ${meta}`].filter(Boolean).join('\n');
}

function formatLibraryItem(item) {
  if (!item) {
    return '';
  }
  const lines = [];
  if (item.title) {
    lines.push(item.title);
  }
  if (item.summary) {
    lines.push(item.summary);
  }
  if (Array.isArray(item.opening_questions) && item.opening_questions.length) {
    lines.push(`Questions : ${item.opening_questions.join(' / ')}`);
  }
  if (item.psychoeducation) {
    lines.push(`Psychoéducation : ${item.psychoeducation}`);
  }
  if (Array.isArray(item.source_contributions) && item.source_contributions.length) {
    lines.push(`Sources : ${item.source_contributions.join(', ')}`);
  }
  return lines.filter(Boolean).join('\n');
}

function updateResearchOutputs(results) {
  if (!refs.researchLocal || !refs.researchWeb || !refs.researchNotes) {
    return;
  }
  if (!results) {
    refs.researchLocal.value = '';
    if (refs.researchLibrary) refs.researchLibrary.value = '';
    refs.researchWeb.value = '';
    refs.researchNotes.value = '';
    state.libraryResults = [];
    return;
  }
  refs.researchLocal.value = serializeResearchList(results.local_library, (item) => {
    return `${item.source} — ${item.extrait}`;
  });
  if (refs.researchLibrary) {
    const libraryItems = results.library || state.libraryResults || [];
    refs.researchLibrary.value = serializeResearchList(libraryItems, formatLibraryItem);
  }
  refs.researchWeb.value = serializeResearchList(results.internet, formatWebResearchItem);
  refs.researchNotes.value = results.notes_integration || '';
}

function restoreRawContextFromStorage() {
  try {
    const mail = localStorage.getItem(STORAGE_KEYS.mail) || '';
    const etat = localStorage.getItem(STORAGE_KEYS.etat) || '';
    const notes = localStorage.getItem(STORAGE_KEYS.notes) || '';
    if (refs.mail) refs.mail.value = mail;
    if (refs.etat) refs.etat.value = etat;
    if (refs.notes) refs.notes.value = notes;
  } catch (error) {
    console.warn('Impossible de restaurer le matériau brut', error);
  }
}

function persistPlan(plan) {
  try {
    localStorage.setItem(STORAGE_KEYS.plan, JSON.stringify(plan || {}));
  } catch (error) {
    console.warn('Impossible de persister le plan', error);
  }
}

function restorePlanFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.plan);
    if (!raw) {
      return;
    }
    const plan = JSON.parse(raw);
    if (plan && typeof plan === 'object') {
      state.plan = plan;
      fillPlanForm(plan);
      updateDiff(plan.diff_avec_plan_precedent);
    }
  } catch (error) {
    console.warn('Impossible de restaurer le plan', error);
  }
}

function persistResearch(results) {
  try {
    localStorage.setItem(STORAGE_KEYS.researchLocal, JSON.stringify(results.local_library || []));
    localStorage.setItem(STORAGE_KEYS.researchWeb, JSON.stringify(results.internet || []));
    localStorage.setItem(STORAGE_KEYS.researchNotes, results.notes_integration || '');
    if (LIBRARY_AUTOSUGGEST) {
      localStorage.setItem(STORAGE_KEYS.researchLibrary, JSON.stringify(results.library || state.libraryResults || []));
    }
  } catch (error) {
    console.warn('Impossible de persister la recherche', error);
  }
}

function restoreResearchFromStorage() {
  try {
    const local = JSON.parse(localStorage.getItem(STORAGE_KEYS.researchLocal) || 'null');
    const web = JSON.parse(localStorage.getItem(STORAGE_KEYS.researchWeb) || 'null');
    const notes = localStorage.getItem(STORAGE_KEYS.researchNotes) || '';
    const library = LIBRARY_AUTOSUGGEST
      ? JSON.parse(localStorage.getItem(STORAGE_KEYS.researchLibrary) || 'null')
      : [];
    if (Array.isArray(local) || Array.isArray(web) || notes) {
      const payload = {
        local_library: Array.isArray(local) ? local : [],
        internet: Array.isArray(web) ? web : [],
        notes_integration: notes,
        library: Array.isArray(library) ? library : [],
      };
      state.research = payload;
      state.libraryResults = payload.library;
      updateResearchOutputs(payload);
    }
  } catch (error) {
    console.warn('Impossible de restaurer la recherche', error);
  }
}

function persistPrompt(value) {
  try {
    localStorage.setItem(STORAGE_KEYS.prompt, value || '');
  } catch (error) {
    console.warn('Impossible de persister le prompt', error);
  }
}

function restorePromptFromStorage() {
  try {
    const prompt = localStorage.getItem(STORAGE_KEYS.prompt) || '';
    if (prompt) {
      state.prompt = prompt;
      if (refs.promptArea) {
        refs.promptArea.value = prompt;
      }
    }
  } catch (error) {
    console.warn('Impossible de restaurer le prompt', error);
  }
}

function clearPrompt() {
  state.prompt = '';
  if (refs.promptArea) {
    refs.promptArea.value = '';
  }
  persistPrompt('');
  updateButtons();
}

async function submitPlan() {
  const rawContext = collectRawContext();
  if (!rawContext.mail_brut) {
    setAlert('alertPlan', 'Merci de renseigner au minimum le mail brut.', 'warning');
    return;
  }
  persistRawContext();
  setAlert('alertPlan', '');
  updateButtons({ busy: true });
  const payload = {
    raw_context: rawContext,
    previous_plan: state.plan || state.previousPlan,
  };
  try {
    const plan = await jsonPost('/api/pre_session/plan', payload);
    state.previousPlan = state.plan;
    state.plan = plan;
    state.rawContext = rawContext;
    fillPlanForm(plan);
    updateDiff(plan.diff_avec_plan_precedent);
    persistPlan(plan);
    state.research = null;
    state.libraryResults = [];
    localStorage.removeItem(STORAGE_KEYS.researchLocal);
    localStorage.removeItem(STORAGE_KEYS.researchWeb);
    localStorage.removeItem(STORAGE_KEYS.researchNotes);
    if (LIBRARY_AUTOSUGGEST) {
      localStorage.removeItem(STORAGE_KEYS.researchLibrary);
      void refreshLibrarySuggestions(plan);
    }
    updateResearchOutputs(null);
    clearPrompt();
    setAlert('alertPlan', 'Plan généré et prêt pour la recherche.', 'info');
  } catch (error) {
    console.error('Plan v3 impossible', error);
    setAlert('alertPlan', error?.message || 'Impossible de générer le plan.', 'error');
  } finally {
    updateButtons({ busy: false });
  }
}

async function submitResearch() {
  if (!state.plan || !state.rawContext) {
    setAlert('alertResearch', 'Génère d’abord un plan pour lancer la recherche.', 'warning');
    return;
  }
  const plan = collectPlanFromForm();
  persistPlan(plan);
  const allowInternet = Boolean(refs.allowInternet?.checked);
  setAlert('alertResearch', '');
  updateButtons({ busy: true });
  try {
    const results = await jsonPost('/api/research', {
      plan,
      raw_context: state.rawContext,
      allow_internet: allowInternet,
    });
    state.plan = plan;
    state.research = results;
    if (LIBRARY_AUTOSUGGEST) {
      await refreshLibrarySuggestions(plan);
      if (state.libraryResults.length) {
        state.research.library = state.libraryResults;
      }
    }
    updateResearchOutputs(results);
    persistResearch(results);
    clearPrompt();
    setAlert('alertResearch', 'Recherche mise à jour avec succès.', 'info');
  } catch (error) {
    console.error('Recherche v3 impossible', error);
    setAlert('alertResearch', error?.message || 'La recherche a échoué.', 'error');
  } finally {
    updateButtons({ busy: false });
  }
}

function buildLibraryQuery(plan) {
  if (!plan) {
    return '';
  }
  const parts = [
    plan.orientation,
    plan.objectif_prioritaire,
    plan.synthese?.tensions_principales,
    plan.synthese?.axes_de_travail,
  ];
  return parts.filter(Boolean).join(' ');
}

async function refreshLibrarySuggestions(plan) {
  if (!LIBRARY_AUTOSUGGEST || !refs.researchLibrary) {
    return;
  }
  if (refs.libraryToggle && !refs.libraryToggle.checked) {
    state.libraryResults = [];
    refs.researchLibrary.value = '';
    if (state.research) {
      state.research.library = [];
    }
    localStorage.removeItem(STORAGE_KEYS.researchLibrary);
    return;
  }
  const query = buildLibraryQuery(plan);
  if (!query) {
    state.libraryResults = [];
    refs.researchLibrary.value = '';
    return;
  }
  try {
    const params = new URLSearchParams({ q: query, mode: 'pre', limit: '6' });
    const response = await fetch(`/library/search?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    const suggestions = Array.isArray(payload?.results) ? payload.results : [];
    state.libraryResults = suggestions;
    if (!state.research) {
      state.research = {
        local_library: [],
        internet: [],
        notes_integration: '',
      };
    }
    state.research.library = suggestions;
    updateResearchOutputs(state.research);
    persistResearch(state.research);
  } catch (error) {
    console.warn('Suggestions bibliothèque indisponibles', error);
  }
}

async function submitPrompt() {
  if (!state.plan || !state.research || !state.rawContext) {
    setAlert('alertPrompt', 'Le plan et la recherche doivent être prêts avant le prompt.', 'warning');
    return;
  }
  const plan = collectPlanFromForm();
  setAlert('alertPrompt', '');
  updateButtons({ busy: true });
  try {
    const payload = await jsonPost('/api/prompt/final', {
      plan,
      research: state.research,
      mail_brut: state.rawContext.mail_brut,
      prenom: '',
    });
    state.plan = plan;
    state.prompt = payload?.prompt || '';
    persistPrompt(state.prompt);
    if (refs.promptArea) {
      refs.promptArea.value = state.prompt;
    }
    setAlert('alertPrompt', 'Prompt final prêt à être copié.', 'info');
  } catch (error) {
    console.error('Prompt final impossible', error);
    setAlert('alertPrompt', error?.message || 'Impossible de composer le prompt final.', 'error');
  } finally {
    updateButtons({ busy: false });
  }
}

async function copyPrompt() {
  if (!state.prompt) {
    return;
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(state.prompt);
    } else {
      const temp = document.createElement('textarea');
      temp.value = state.prompt;
      document.body.appendChild(temp);
      temp.select();
      document.execCommand('copy');
      document.body.removeChild(temp);
    }
    setAlert('alertPrompt', 'Prompt copié dans le presse-papiers.', 'info');
  } catch (error) {
    console.error('Copie impossible', error);
    setAlert('alertPrompt', "Impossible de copier le prompt.", 'error');
  }
}

function exportPrompt() {
  if (!state.prompt) {
    return;
  }
  try {
    const blob = new Blob([state.prompt], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'prompt-final.txt';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    setAlert('alertPrompt', 'Fichier .txt exporté.', 'info');
  } catch (error) {
    console.error('Export impossible', error);
    setAlert('alertPrompt', "Impossible d'exporter le prompt.", 'error');
  }
}

function resetAfterContextChange() {
  state.rawContext = null;
  state.plan = null;
  state.previousPlan = null;
  state.research = null;
  state.libraryResults = [];
  state.prompt = '';
  updateButtons();
  fillPlanForm(null);
  updateDiff(null);
  updateResearchOutputs(null);
  clearPrompt();
  localStorage.removeItem(STORAGE_KEYS.plan);
  localStorage.removeItem(STORAGE_KEYS.researchLocal);
  localStorage.removeItem(STORAGE_KEYS.researchWeb);
  localStorage.removeItem(STORAGE_KEYS.researchNotes);
  if (LIBRARY_AUTOSUGGEST) {
    localStorage.removeItem(STORAGE_KEYS.researchLibrary);
  }
  setAlert('alertPlan', 'Relance la validation du plan après modifications.', 'info');
  setAlert('alertResearch', '');
  setAlert('alertPrompt', '');
}

function bindEvents() {
  if (!container) {
    return;
  }
  container.addEventListener('input', (event) => {
    if (event.target === refs.mail || event.target === refs.etat || event.target === refs.notes) {
      persistRawContext();
      resetAfterContextChange();
    }
  });
  container.addEventListener('click', (event) => {
    const { target } = event;
    if (target === refs.planButton) {
      event.preventDefault();
      void submitPlan();
    } else if (target === refs.researchButton) {
      event.preventDefault();
      void submitResearch();
    } else if (target === refs.promptButton) {
      event.preventDefault();
      void submitPrompt();
    } else if (target === refs.copyButton) {
      event.preventDefault();
      void copyPrompt();
    } else if (target === refs.exportButton) {
      event.preventDefault();
      exportPrompt();
    }
  });
  if (refs.libraryToggle && LIBRARY_AUTOSUGGEST) {
    refs.libraryToggle.addEventListener('change', () => {
      void refreshLibrarySuggestions(state.plan || collectPlanFromForm());
    });
  }
}

function handlePatientChange() {
  if (refs.mail) refs.mail.value = '';
  if (refs.etat) refs.etat.value = '';
  if (refs.notes) refs.notes.value = '';
  Object.values(STORAGE_KEYS).forEach((key) => localStorage.removeItem(key));
  resetAfterContextChange();
}

export function init() {
  if (initialized) {
    return;
  }
  container = document.querySelector('section[data-tab="pre_session"]');
  if (!container) {
    return;
  }
  ensureStyle();
  const version = window.ASSET_VERSION ? `?v=${encodeURIComponent(window.ASSET_VERSION)}` : '';
  fetch(`/static/tabs/pre_session/view.html${version}`)
    .then((response) => response.text())
    .then((html) => {
      container.innerHTML = html;
      mapRefs();
      bindEvents();
      restoreRawContextFromStorage();
      restorePlanFromStorage();
      restoreResearchFromStorage();
      restorePromptFromStorage();
      state.rawContext = collectRawContext();
      updateButtons();
    })
    .catch((error) => {
      console.error('Impossible de charger la vue Pré-séance v3', error);
    });
  unsubscribePatient = subscribeState('selectedPatientId', handlePatientChange);
  initialized = true;
}

export function show() {
  if (container) {
    container.classList.remove('hidden');
  }
}

export function hide() {
  if (container) {
    container.classList.add('hidden');
  }
}

export function destroy() {
  if (unsubscribePatient) {
    unsubscribePatient();
    unsubscribePatient = null;
  }
  container = null;
  initialized = false;
  state.rawContext = null;
  state.plan = null;
  state.previousPlan = null;
  state.research = null;
  state.prompt = '';
}
// # [pipeline-v3 end]
