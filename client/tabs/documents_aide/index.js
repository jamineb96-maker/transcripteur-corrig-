import { get as getState, set as setState, subscribe } from '../../services/app_state.js';
import { jsonGet, jsonPost, API_BASE } from '../../services/api.js';
import { withAssetVersion } from '../../services/assets.js';
import { validateTab } from '../../services/tab_validator.js';

const VIEW_URL = '/static/tabs/documents_aide/view.html';
const STYLE_URL = '/static/tabs/documents_aide/style.css';
const SCRIPT_URL = '/static/tabs/documents_aide/index.js';
const MODULE_ID = 'documents_aide';

const REQUIRED_DOM = {
  patientSelect: '#docAidePatientSelect',
  newButton: '#docAideNewButton',
  catalogGrid: '#docAideCatalogGrid',
  search: '#docAideSearch',
  categoryFilter: '#docAideCategoryFilter',
  historyBody: '#docAideHistoryBody',
  refreshHistory: '#docAideRefreshHistory',
  profileBlock: '#docAideProfileBlock',
  suggestionsBlock: '#docAideSuggestions',
  lastNotesBlock: '#docAideLastNotes',
  wizard: '#docAideWizard',
  formContainer: '#docAideFormContainer',
  previewFrame: '#docAidePreview',
  formatSelect: '#docAideFormat',
  generateBtn: '#docAideGenerate',
  pronounSelect: '#docAidePronoun',
  genderSelect: '#docAideGender',
  tvSelect: '#docAideTV',
  wizardTitle: '#docAideWizardTitle',
  wizardSteps: { selector: '.wizard-steps button', mode: 'all', min: 1 },
  diagnostics: '#docAideDiagnostics',
};

const REQUIRED_SELECTORS = Array.from(
  new Set(
    Object.values(REQUIRED_DOM).map((entry) => (typeof entry === 'string' ? entry : entry.selector)),
  ),
);

let container;
let initialized = false;
let unsubscribePatient;
let unsubscribePatientsCache;

const state = {
  templates: [],
  patientId: '',
  profile: null,
  context: {},
  suggestions: [],
  history: [],
  filter: '',
  category: '',
  wizard: {
    template: null,
    inputs: {},
    step: 1,
    busy: false,
  },
};

const refs = {};

class ModuleSetupError extends Error {
  constructor(step, details = {}) {
    super(`${MODULE_ID}:${step}`);
    this.name = 'DocumentsAideInitError';
    this.step = step;
    this.details = details;
  }
}

function logModuleError(step, details = {}) {
  console.error({ module: MODULE_ID, step, ...details });
}

function resetRefs() {
  Object.keys(refs).forEach((key) => {
    delete refs[key];
  });
}

function ensureStylesheet() {
  const href = withAssetVersion(STYLE_URL);
  const absoluteHref = new URL(href, window.location.origin).href;
  const selector = 'link[data-style="documents_aide"]';
  let link = document.querySelector(selector);
  if (!link) {
    link = document.createElement('link');
    link.rel = 'stylesheet';
    link.dataset.style = 'documents_aide';
    document.head.appendChild(link);
  }
  if (link.href !== absoluteHref) {
    link.href = absoluteHref;
  }
}

function mapRefs() {
  if (!container) return [];
  resetRefs();
  const missing = [];
  Object.entries(REQUIRED_DOM).forEach(([key, definition]) => {
    const config = typeof definition === 'string' ? { selector: definition } : definition;
    const { selector, mode = 'single', min = 1 } = config;
    if (mode === 'all') {
      const nodes = container.querySelectorAll(selector);
      if (!nodes || nodes.length < min) {
        missing.push(selector);
      } else {
        refs[key] = nodes;
      }
      return;
    }
    const node = container.querySelector(selector);
    if (!node) {
      missing.push(selector);
    } else {
      refs[key] = node;
    }
  });
  return missing;
}

function clearDiagnostics() {
  if (refs.diagnostics) {
    refs.diagnostics.hidden = true;
    refs.diagnostics.textContent = '';
  }
}

function showDiagnostics(result) {
  if (!refs.diagnostics) {
    return;
  }
  const messages = [];
  if (result.missingAssets?.length) {
    const assets = result.missingAssets
      .map((asset) => (typeof asset === 'string' ? asset : `${asset.url} (${asset.reason || 'inconnu'})`))
      .join(', ');
    messages.push(`Assets introuvables : ${assets}`);
  }
  if (result.missingSelectors?.length) {
    messages.push(`Sélecteurs manquants : ${result.missingSelectors.join(', ')}`);
  }
  if (result.duplicates?.length) {
    messages.push(`Doublons de dossiers détectés : ${result.duplicates.join(', ')}`);
  }
  if (!messages.length) {
    refs.diagnostics.hidden = true;
    refs.diagnostics.textContent = '';
    return;
  }
  const list = document.createElement('ul');
  messages.forEach((text) => {
    const item = document.createElement('li');
    item.textContent = text;
    list.appendChild(item);
  });
  refs.diagnostics.innerHTML = '<strong>Diagnostic Documents d’aide</strong>';
  refs.diagnostics.appendChild(list);
  refs.diagnostics.hidden = false;
}

async function validateModuleIntegrity() {
  try {
    const result = await validateTab(MODULE_ID, {
      assets: [SCRIPT_URL, VIEW_URL, STYLE_URL],
      selectors: REQUIRED_SELECTORS,
    });
    if (result?.ran && (result.missingAssets.length || result.missingSelectors.length || result.duplicates.length)) {
      showDiagnostics(result);
    } else if (result?.ran) {
      clearDiagnostics();
    }
  } catch (error) {
    logModuleError('validateTab', { error });
  }
}

function bindEvents() {
  refs.search?.addEventListener('input', (event) => {
    state.filter = event.target.value || '';
    renderCatalog();
  });
  refs.categoryFilter?.addEventListener('change', (event) => {
    state.category = event.target.value || '';
    renderCatalog();
  });
  refs.refreshHistory?.addEventListener('click', () => {
    if (state.patientId) {
      void loadHistory(state.patientId);
    }
  });
  refs.newButton?.addEventListener('click', () => {
    if (!state.templates.length) return;
    openWizard(state.templates[0]);
  });
  refs.patientSelect?.addEventListener('change', (event) => {
    const value = event.target.value;
    applySelectedPatient(value);
  });
  refs.generateBtn?.addEventListener('click', () => {
    void finalizeGeneration();
  });
  refs.pronounSelect?.addEventListener('change', () => {
    if (state.wizard.step >= 2) {
      void refreshPreview();
    }
  });
  refs.genderSelect?.addEventListener('change', () => {
    if (state.wizard.step >= 2) {
      void refreshPreview();
    }
  });
  refs.tvSelect?.addEventListener('change', () => {
    if (state.wizard.step >= 2) {
      void refreshPreview();
    }
  });
  refs.wizardSteps?.forEach((button) => {
    button.addEventListener('click', () => {
      const step = Number(button.dataset.step || '1');
      setWizardStep(step);
    });
  });
  refs.wizard?.addEventListener('close', () => {
    state.wizard.template = null;
    state.wizard.inputs = {};
    state.wizard.step = 1;
    state.wizard.busy = false;
  });
}

async function loadView() {
  const url = withAssetVersion(VIEW_URL);
  let response;
  try {
    response = await fetch(url);
  } catch (error) {
    throw new ModuleSetupError('fetch', { url, error });
  }
  if (!response.ok) {
    throw new ModuleSetupError('http', { url, status: response.status });
  }
  const html = await response.text();
  container.innerHTML = html;
  ensureStylesheet();
  const missing = mapRefs();
  if (missing.length) {
    throw new ModuleSetupError('selectors', { url, missingSelectors: missing });
  }
  clearDiagnostics();
  bindEvents();
  void validateModuleIntegrity();
}

function describeSetupError(error) {
  if (error instanceof ModuleSetupError) {
    if (error.step === 'fetch') {
      const message = error.details?.error?.message || 'Erreur réseau inconnue.';
      return {
        step: error.step,
        title: 'Chargement de la vue impossible',
        message: `La requête vers ${error.details?.url || 'la vue HTML'} a échoué : ${message}`,
        code: `${MODULE_ID}:${error.step}`,
        log: { url: error.details?.url, cause: error.details?.error },
      };
    }
    if (error.step === 'http') {
      return {
        step: error.step,
        title: 'Réponse serveur inattendue',
        message: `Le serveur a répondu ${error.details?.status} pour ${error.details?.url}.`,
        code: `${MODULE_ID}:${error.step}`,
        log: { url: error.details?.url, status: error.details?.status },
      };
    }
    if (error.step === 'selectors') {
      const missingSelectors = error.details?.missingSelectors || [];
      return {
        step: error.step,
        title: 'Structure du module invalide',
        message: 'La vue chargée ne contient pas tous les sélecteurs requis.',
        items: missingSelectors,
        code: `${MODULE_ID}:${error.step}`,
        log: { url: error.details?.url, missingSelectors },
      };
    }
  }
  return {
    step: 'init',
    title: 'Module Documents d’aide indisponible',
    message: 'Une erreur inattendue a interrompu l’initialisation.',
    code: `${MODULE_ID}:init`,
    log: { error },
  };
}

function renderLoadFailure(error) {
  if (!container) {
    return;
  }
  clearDiagnostics();
  const info = describeSetupError(error);
  logModuleError(info.step, info.log);
  const parts = [
    '<div class="documents-aide__error">',
    `<h2>${info.title}</h2>`,
    `<p>${info.message}</p>`,
  ];
  if (info.items?.length) {
    parts.push('<ul>');
    info.items.forEach((item) => {
      parts.push(`<li><code>${item}</code></li>`);
    });
    parts.push('</ul>');
  }
  parts.push(`<p class="documents-aide__error-code"><code>${info.code}</code></p>`);
  parts.push('</div>');
  container.innerHTML = parts.join('');
}

function populatePatients() {
  if (!refs.patientSelect) return;
  refs.patientSelect.innerHTML = '';
  const patients = getState('patientsCache') || [];
  const fragment = document.createDocumentFragment();
  patients.forEach((patient) => {
    const option = document.createElement('option');
    option.value = patient.id;
    option.textContent = patient.displayName || patient.id;
    fragment.appendChild(option);
  });
  refs.patientSelect.appendChild(fragment);
  if (state.patientId) {
    refs.patientSelect.value = state.patientId;
  }
}

async function loadTemplates() {
  try {
    const response = await jsonGet('/api/documents-aide/templates');
    state.templates = Array.isArray(response.templates) ? response.templates : [];
    populateCategories();
    renderCatalog();
  } catch (error) {
    logModuleError('loadTemplates', { error });
  }
}

function populateCategories() {
  if (!refs.categoryFilter) return;
  const categories = Array.from(new Set(state.templates.map((tpl) => tpl.category).filter(Boolean))).sort();
  refs.categoryFilter.innerHTML = '<option value="">Toutes les catégories</option>';
  categories.forEach((category) => {
    const option = document.createElement('option');
    option.value = category;
    option.textContent = category;
    refs.categoryFilter.appendChild(option);
  });
}

function renderCatalog() {
  if (!refs.catalogGrid) return;
  refs.catalogGrid.innerHTML = '';
  const query = (state.filter || '').toLowerCase();
  const selectedCategory = state.category || '';
  const filtered = state.templates.filter((tpl) => {
    const haystack = `${tpl.title} ${tpl.category}`.toLowerCase();
    const matchesQuery = !query || haystack.includes(query);
    const matchesCategory = !selectedCategory || tpl.category === selectedCategory;
    return matchesQuery && matchesCategory;
  });
  if (!filtered.length) {
    const empty = document.createElement('p');
    empty.className = 'catalog-empty';
    empty.textContent = 'Aucun modèle ne correspond à votre recherche.';
    refs.catalogGrid.appendChild(empty);
    return;
  }
  filtered.forEach((template) => {
    const card = document.createElement('article');
    card.className = 'catalog-card';
    card.innerHTML = `
      <div class="card-category">${template.category || ''}</div>
      <h3>${template.title}</h3>
      <p class="card-description">${describeTemplate(template)}</p>
      <button type="button" class="btn ghost">Créer</button>
    `;
    const button = card.querySelector('button');
    button.addEventListener('click', () => openWizard(template));
    refs.catalogGrid.appendChild(card);
  });
}

function describeTemplate(template) {
  switch (template.id) {
    case 'fatigue_eval':
      return 'Grille 0-5 pour suivre la fatigue et les signaux différés.';
    case 'couts_energie':
      return 'Visualiser les contextes qui rechargent ou coûtent de l’énergie.';
    case 'pauses_sensorielles':
      return 'Planifier des mini-rituels sensoriels et leur checklist.';
    case 'deadlines_souples':
      return 'Structurer une deadline souple avec jalons et plan B.';
    case 'carte_couts_invisibles':
      return 'Lister les coûts invisibles et estimer les cuillères dépensées.';
    case 'grille_cause_consequence':
      return 'Tracer les liens entre situation, réaction et besoins.';
    default:
      return '';
  }
}

async function loadContext(patientId) {
  if (!patientId) return;
  try {
    const response = await jsonGet(`/api/documents-aide/context?patient=${encodeURIComponent(patientId)}`);
    state.profile = response.profile || null;
    state.context = response.context || {};
    state.suggestions = Array.isArray(response.suggestions) ? response.suggestions : [];
    renderContext();
  } catch (error) {
    logModuleError('loadContext', { error, patientId });
  }
}

async function loadHistory(patientId) {
  if (!patientId) {
    state.history = [];
    renderHistory();
    return;
  }
  try {
    const response = await jsonGet(`/api/documents-aide?patient=${encodeURIComponent(patientId)}`);
    state.history = Array.isArray(response.history) ? response.history : [];
    renderHistory();
  } catch (error) {
    logModuleError('loadHistory', { error, patientId });
  }
}

function renderContext() {
  if (refs.profileBlock) {
    const profile = state.profile || {};
    refs.profileBlock.innerHTML = `
      <strong>${profile.full_name || profile.display_name || profile.displayName || 'Patient·e'}</strong>
      <span>Pronom : ${profile.pronoun || 'elle'}</span>
      <span>Genre : ${profile.gender || 'f'}</span>
      <span>Adresse : ${profile.tv || 'tu'}</span>
    `;
  }
  if (refs.suggestionsBlock) {
    refs.suggestionsBlock.innerHTML = '<h3>Suggestions</h3>';
    const list = document.createElement('ul');
    list.className = 'context-list';
    if (!state.suggestions.length) {
      const item = document.createElement('li');
      item.textContent = 'Aucune suggestion récente.';
      list.appendChild(item);
    } else {
      state.suggestions.forEach((text) => {
        const item = document.createElement('li');
        item.textContent = text;
        list.appendChild(item);
      });
    }
    refs.suggestionsBlock.appendChild(list);
  }
  if (refs.lastNotesBlock) {
    refs.lastNotesBlock.innerHTML = '<h3>Dernières notes</h3>';
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(state.context?.last_notes || {}, null, 2);
    refs.lastNotesBlock.appendChild(pre);
  }
  if (refs.pronounSelect && state.profile) {
    refs.pronounSelect.value = state.profile.pronoun || refs.pronounSelect.value;
    refs.genderSelect.value = state.profile.gender || refs.genderSelect.value;
    refs.tvSelect.value = state.profile.tv || refs.tvSelect.value;
  }
}

function renderHistory() {
  if (!refs.historyBody) return;
  refs.historyBody.innerHTML = '';
  if (!state.history.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 6;
    cell.textContent = 'Aucun document sauvegardé pour le moment.';
    row.appendChild(cell);
    refs.historyBody.appendChild(row);
    return;
  }
  state.history.forEach((entry) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${entry.title || entry.file}</td>
      <td>${entry.template || ''}</td>
      <td>${formatDate(entry.created)}</td>
      <td>${(entry.format || '').toUpperCase()}</td>
      <td>${formatSize(entry.bytes)}</td>
      <td class="history-actions"></td>
    `;
    const actionsCell = row.querySelector('.history-actions');
    if (actionsCell) {
      const downloadBtn = document.createElement('button');
      downloadBtn.type = 'button';
      downloadBtn.className = 'btn ghost';
      downloadBtn.textContent = 'Télécharger';
      downloadBtn.addEventListener('click', () => {
        window.open(`${API_BASE}${entry.path}`, '_blank');
      });
      const renameBtn = document.createElement('button');
      renameBtn.type = 'button';
      renameBtn.className = 'btn ghost';
      renameBtn.textContent = 'Renommer';
      renameBtn.addEventListener('click', () => renameEntry(entry));
      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'btn danger ghost';
      deleteBtn.textContent = 'Supprimer';
      deleteBtn.addEventListener('click', () => deleteEntry(entry));
      actionsCell.append(downloadBtn, renameBtn, deleteBtn);
    }
    refs.historyBody.appendChild(row);
  });
}

function formatDate(value) {
  if (!value) return '';
  try {
    const date = new Date(value);
    return date.toLocaleString('fr-FR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch (error) {
    return value;
  }
}

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '';
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
}

function openWizard(template) {
  if (!template || !refs.wizard) return;
  state.wizard.template = template;
  state.wizard.inputs = { ...computePrefill(template) };
  state.wizard.step = 1;
  state.wizard.busy = false;
  renderForm(template);
  setWizardStep(1, { silent: true });
  refs.wizardTitle.textContent = template.title;
  if (typeof refs.wizard.showModal === 'function') {
    refs.wizard.showModal();
  }
}

function renderForm(template) {
  if (!refs.formContainer) return;
  refs.formContainer.innerHTML = '';
  (template.inputs || []).forEach((input) => {
    const label = document.createElement('label');
    label.dataset.field = input.name;
    label.innerHTML = `<span>${input.label}</span>`;
    let field;
    const value = state.wizard.inputs[input.name] ?? '';
    if (input.type === 'textarea') {
      field = document.createElement('textarea');
      field.value = value;
    } else if (input.type === 'checkbox') {
      field = document.createElement('input');
      field.type = 'checkbox';
      field.checked = Boolean(value);
    } else {
      field = document.createElement('input');
      field.type = input.type || 'text';
      field.value = value;
      if (typeof input.min !== 'undefined') field.min = input.min;
      if (typeof input.max !== 'undefined') field.max = input.max;
    }
    field.name = input.name;
    field.addEventListener('input', () => updateWizardInput(input, field));
    field.addEventListener('change', () => updateWizardInput(input, field));
    label.appendChild(field);
    refs.formContainer.appendChild(label);
  });
}

function updateWizardInput(input, field) {
  if (input.type === 'checkbox') {
    state.wizard.inputs[input.name] = field.checked;
  } else {
    state.wizard.inputs[input.name] = field.value;
  }
  if (state.wizard.step >= 2) {
    void refreshPreview();
  }
}

function setWizardStep(step, options = {}) {
  const { silent = false } = options;
  state.wizard.step = step;
  refs.wizardSteps?.forEach((button) => {
    button.classList.toggle('active', Number(button.dataset.step) === step);
  });
  const panels = refs.wizard?.querySelectorAll('.wizard-step');
  panels?.forEach((panel) => {
    panel.classList.toggle('active', Number(panel.dataset.step) === step);
  });
  if (step === 1 && refs.previewFrame) {
    refs.previewFrame.srcdoc = '<p class="preview-placeholder">Complétez les champs pour afficher un aperçu.</p>';
  }
  if (!silent && step === 2) {
    void refreshPreview();
  }
}

async function refreshPreview() {
  if (!state.patientId || !state.wizard.template) return;
  try {
    const payload = buildPayload({ preview: true });
    const response = await jsonPost(`/api/documents-aide/generate?preview=true`, payload);
    if (refs.previewFrame) {
      refs.previewFrame.srcdoc = response.html || '<p>Aperçu indisponible.</p>';
    }
  } catch (error) {
    logModuleError('preview', { error });
    if (refs.previewFrame) {
      refs.previewFrame.srcdoc = '<p>Erreur lors du rendu de l’aperçu.</p>';
    }
  }
}

function buildPayload(extra = {}) {
  const override_profile = {
    pronoun: refs.pronounSelect?.value || undefined,
    gender: refs.genderSelect?.value || undefined,
    tv: refs.tvSelect?.value || undefined,
  };
  return {
    patient: state.patientId,
    template_id: state.wizard.template?.id,
    inputs: state.wizard.inputs,
    format: refs.formatSelect?.value || 'pdf',
    override_profile,
    ...extra,
  };
}

async function finalizeGeneration() {
  if (!state.wizard.template || !state.patientId) {
    return;
  }
  try {
    state.wizard.busy = true;
    refs.generateBtn.disabled = true;
    refs.generateBtn.textContent = 'Génération…';
    const payload = buildPayload();
    const response = await jsonPost('/api/documents-aide/generate', payload);
    if (response?.entry) {
      await loadHistory(state.patientId);
    }
    if (refs.wizard && typeof refs.wizard.close === 'function') {
      refs.wizard.close();
    }
    state.wizard.busy = false;
  } catch (error) {
    logModuleError('generate', { error });
  } finally {
    if (refs.generateBtn) {
      refs.generateBtn.disabled = false;
      refs.generateBtn.textContent = 'Générer et archiver';
    }
  }
}

async function deleteEntry(entry) {
  if (!entry || !state.patientId) return;
  const confirmDelete = window.confirm('Supprimer ce document ?');
  if (!confirmDelete) return;
  try {
    const resp = await fetch(
      `${API_BASE}/api/documents-aide/${encodeURIComponent(state.patientId)}/${encodeURIComponent(entry.file)}`,
      {
        method: 'DELETE',
        headers: { Accept: 'application/json' },
      },
    );
    if (!resp.ok) {
      throw new Error('Suppression impossible');
    }
    await loadHistory(state.patientId);
  } catch (error) {
    logModuleError('deleteEntry', { error, entry });
  }
}

async function renameEntry(entry) {
  if (!entry || !state.patientId) return;
  const next = window.prompt('Nouveau titre', entry.title || '');
  if (!next) return;
  try {
    await jsonPost('/api/documents-aide/rename', {
      patient: state.patientId,
      file: entry.file,
      title: next,
    });
    await loadHistory(state.patientId);
  } catch (error) {
    logModuleError('renameEntry', { error, entry });
  }
}

function computePrefill(template) {
  const context = state.context || {};
  const lastPlan = context.last_plan || {};
  const nextMorning = context.next_morning || {};
  const energy = context.energy || {};
  const pauses = context.pauses || {};
  const deadlines = context.deadlines || {};
  const couts = context.couts || {};
  const grille = context.grille || {};
  const defaults = {};
  switch (template.id) {
    case 'fatigue_eval':
      defaults.activite = lastPlan.activity || lastPlan.focus || '';
      defaults.date = context.last_activity_date || '';
      defaults.imm_commentaire = context.last_immediate_note || '';
      defaults.lendemain_reveil = nextMorning.reveil || '';
      defaults.lendemain_tensions = nextMorning.tensions || '';
      defaults.lendemain_clarte = nextMorning.clarte || '';
      defaults.lendemain = nextMorning.notes || '';
      defaults.lendemain_actions = nextMorning.suggestions || '';
      break;
    case 'couts_energie':
      defaults.contextes_plus2 = energy.plus2 || '';
      defaults.contextes_moins2 = energy.moins2 || '';
      defaults.signaux_corp = energy.signaux_corp || '';
      defaults.signaux_emo = energy.signaux_emo || '';
      defaults.signaux_arret = energy.signaux_arret || '';
      break;
    case 'pauses_sensorielles':
      (pauses.rituels || []).forEach((rituel, index) => {
        const base = index + 1;
        defaults[`rituel_${base}`] = rituel?.titre || '';
        defaults[`duree_${base}`] = rituel?.duree || '';
        defaults[`frequence_${base}`] = rituel?.frequence || '';
        defaults[`materiel_${base}`] = rituel?.materiel || '';
      });
      if (pauses.options) {
        defaults.opt_silence = Boolean(pauses.options.silence);
        defaults.opt_lumiere = Boolean(pauses.options.lumiere);
        defaults.opt_contact = Boolean(pauses.options.contact);
        defaults.opt_proprio = Boolean(pauses.options.proprio);
        defaults.opt_odeur = Boolean(pauses.options.odeur);
        defaults.opt_mouvement = Boolean(pauses.options.mouvement);
      }
      defaults.trousse = pauses.trousse || '';
      break;
    case 'deadlines_souples':
      (deadlines.jalons || []).forEach((jalon, index) => {
        const base = index + 1;
        defaults[`jalon_${base}`] = jalon?.titre || '';
        defaults[`deadline_${base}`] = jalon?.deadline || '';
        defaults[`fenetre_${base}`] = jalon?.fenetre || '';
        defaults[`planb_${base}`] = jalon?.planB || '';
      });
      defaults.communication = deadlines.communication || '';
      defaults.signaux = deadlines.signaux || '';
      break;
    case 'carte_couts_invisibles':
      defaults.cout_masquage = Boolean(couts.masquage);
      defaults.cout_social = Boolean(couts.social);
      defaults.cout_imprevus = Boolean(couts.imprevus);
      defaults.cout_sensoriel = Boolean(couts.sensoriel);
      defaults.cout_recup = Boolean(couts.recuperation);
      defaults.cout_admin = Boolean(couts.administratif);
      defaults.cuilleres = couts.cuilleres || '';
      defaults.strategies = couts.strategies || '';
      break;
    case 'grille_cause_consequence':
      (grille.lignes || []).forEach((ligne, index) => {
        const base = index + 1;
        defaults[`situation_${base}`] = ligne?.situation || '';
        defaults[`ressenti_${base}`] = ligne?.ressenti || '';
        defaults[`reaction_${base}`] = ligne?.reaction || '';
        defaults[`consequence_${base}`] = ligne?.consequence || '';
        defaults[`besoin_${base}`] = ligne?.besoin || '';
      });
      defaults.observations = grille.observations || '';
      break;
    default:
      break;
  }
  return defaults;
}

function applySelectedPatient(patientId) {
  state.patientId = patientId || '';
  if (refs.patientSelect && refs.patientSelect.value !== state.patientId) {
    refs.patientSelect.value = state.patientId;
  }
  if (!patientId) {
    renderContext();
    renderHistory();
    return;
  }
  const globalSelect = document.getElementById('patientSelect');
  if (globalSelect && globalSelect.value !== patientId) {
    globalSelect.value = patientId;
  }
  setState('selectedPatientId', patientId);
  window.dispatchEvent(
    new CustomEvent('patient:changed', {
      detail: { id: patientId },
    }),
  );
  void loadContext(patientId);
  void loadHistory(patientId);
}

export function init() {
  if (initialized) return;
  container = document.querySelector('section[data-tab="documents_aide"]');
  if (!container) return;
  void (async () => {
    try {
      await loadView();
      populatePatients();
      unsubscribePatientsCache = subscribe('patientsCache', () => {
        populatePatients();
      });
      const currentPatient = getState('selectedPatientId');
      if (currentPatient) {
        state.patientId = currentPatient;
        refs.patientSelect.value = currentPatient;
        void loadContext(currentPatient);
        void loadHistory(currentPatient);
      }
      void loadTemplates();
      unsubscribePatient = subscribe('selectedPatientId', (next) => {
        if (next && next !== state.patientId) {
          state.patientId = next;
          if (refs.patientSelect) {
            refs.patientSelect.value = next;
          }
          void loadContext(next);
          void loadHistory(next);
        }
      });
      initialized = true;
    } catch (error) {
      initialized = false;
      renderLoadFailure(error);
    }
  })();
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
    unsubscribePatient = undefined;
  }
  if (unsubscribePatientsCache) {
    unsubscribePatientsCache();
    unsubscribePatientsCache = undefined;
  }
  initialized = false;
}
