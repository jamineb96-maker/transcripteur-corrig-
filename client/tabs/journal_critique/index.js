import { jsonGet, jsonPost } from '../../services/api.js';
import { get as getState } from '../../services/app_state.js';
import { initEntriesManager, reloadEntries } from './entries_manager.js';

const DOMAINS = ['somatique', 'cognitif', 'relationnel', 'politique', 'valeurs'];
const STORAGE_PREFIX = 'journal:v1:';

let container;
let initialized = false;
const elements = {};

const state = {
  prompts: [],
  promptsIndex: new Map(),
  filteredIds: [],
  selected: [],
  langage: 'tu',
  genre: 'neutral',
  budget: 'moyen',
  artefacts: {},
  rawArtefacts: '',
  notes: '',
  coverage: { scores: {}, alerts: [] },
  history: [],
  searchQuery: '',
  suggestions: [],
  recommendations: {},
  patientId: null,
  patientName: '',
};

export function init() {
  if (initialized) return;
  container = document.querySelector('section[data-tab="journal_critique"]');
  if (!container) return;

  const version = window.ASSET_VERSION || '';
  fetch(`/static/tabs/journal_critique/view.html?v=${version}`)
    .then((resp) => resp.text())
    .then((html) => {
      container.innerHTML = html;
      injectStyle(version);
      cacheElements();
      initEntriesManager(container.querySelector('[data-journal-app]'));
      bindEvents();
      restorePatient();
      fetchPrompts();
      fetchRecommendations('somatique');
      fetchRecommendations('cognitif');
      fetchRecommendations('relationnel');
      fetchRecommendations('politique');
      fetchRecommendations('valeurs');
      initialized = true;
    })
    .catch((err) => {
      console.error(err);
      setStatus('Impossible de charger l’onglet Journal critique.');
    });

  window.addEventListener('patient:changed', handlePatientChange);
}

export function show() {
  if (!container) return;
  container.classList.remove('hidden');
  if (!initialized) return;
  restorePatient();
  void reloadEntries();
  fetchHistory();
  updateChargeIndicator();
}

export function hide() {
  if (container) {
    container.classList.add('hidden');
  }
}

function injectStyle(version) {
  const href = `/static/tabs/journal_critique/style.css?v=${version}`;
  if (!document.querySelector(`link[href="${href}"]`)) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }
}

function cacheElements() {
  elements.status = container.querySelector('[data-status]');
  elements.search = container.querySelector('[data-field="search"]');
  elements.promptsList = container.querySelector('[data-prompts-list]');
  elements.suggestions = container.querySelector('[data-suggestions]');
  elements.selectedList = container.querySelector('[data-selected-list]');
  elements.coverage = container.querySelector('[data-coverage]');
  elements.alerts = container.querySelector('[data-alerts]');
  elements.artefacts = container.querySelector('[data-field="artefacts"]');
  elements.notes = container.querySelector('[data-field="notes"]');
  elements.preview = container.querySelector('[data-preview]');
  elements.previewOutput = container.querySelector('[data-preview-output]');
  elements.history = container.querySelector('[data-history-list]');
  elements.chargeValue = container.querySelector('[data-charge-value]');
  elements.recommendations = container.querySelector('[data-recommendations]');
}

function bindEvents() {
  container.addEventListener('input', handleInput);
  container.addEventListener('change', handleChange);
  container.addEventListener('click', handleClick);
}

function handleInput(event) {
  const { target } = event;
  if (!target) return;
  if (target === elements.search) {
    state.searchQuery = target.value || '';
    filterPrompts();
    renderPrompts();
  } else if (target === elements.artefacts) {
    state.rawArtefacts = target.value || '';
  } else if (target === elements.notes) {
    state.notes = target.value || '';
  }
}

function handleChange(event) {
  const { target } = event;
  if (!target) return;
  const field = target.getAttribute('data-field');
  if (field === 'langage' && target.checked) {
    state.langage = target.value;
    savePreferences();
  }
  if (field === 'genre' && target.checked) {
    state.genre = target.value;
    savePreferences();
  }
  if (field === 'budget' && target.checked) {
    state.budget = target.value;
    savePreferences();
    updateChargeIndicator();
    if (state.selected.length) {
      updateCoverage();
    }
  }
}

function handleClick(event) {
  const button = event.target.closest('button');
  if (!button) {
    const suggestion = event.target.closest('.suggestion-chip');
    if (suggestion) {
      const id = suggestion.dataset.id;
      if (id) {
        addPrompt(id);
      }
    }
    return;
  }
  const action = button.getAttribute('data-action');
  if (action === 'refresh-prompts') {
    fetchPrompts();
  }
  if (action === 'fetch-suggestions') {
    fetchSuggestions();
  }
  if (action === 'add-prompt') {
    const id = button.dataset.id;
    addPrompt(id);
  }
  if (action === 'remove-prompt') {
    const id = button.dataset.id;
    removePrompt(id);
  }
  if (action === 'parse-artefacts') {
    parseArtefacts();
  }
  if (action === 'preview') {
    handlePreview();
  }
  if (action === 'generate') {
    handleGenerate();
  }
  if (action === 'clear-selection') {
    clearSelection();
  }
}

function setStatus(message) {
  if (elements.status) {
    elements.status.textContent = message || '';
  }
}

async function fetchPrompts() {
  try {
    setStatus('Chargement des prompts…');
    const data = await jsonGet('/api/journal-critique/prompts');
    state.prompts = Array.isArray(data.prompts) ? data.prompts : [];
    state.promptsIndex = new Map();
    state.prompts.forEach((prompt) => {
      state.promptsIndex.set(prompt.id, prompt);
    });
    filterPrompts();
    renderPrompts();
    setStatus(state.prompts.length ? 'Prompts chargés.' : 'Aucun prompt disponible.');
  } catch (error) {
    console.error(error);
    setStatus('Impossible de charger les prompts.');
  }
}

function filterPrompts() {
  const query = (state.searchQuery || '').trim().toLowerCase();
  const selectedIds = new Set(state.selected.map((item) => item.id));
  const filtered = [];
  state.prompts.forEach((prompt) => {
    if (selectedIds.has(prompt.id)) {
      return;
    }
    if (!query) {
      filtered.push(prompt.id);
      return;
    }
    const haystack = [
      prompt.title,
      prompt.family,
      (prompt.familyLabel || ''),
      ...(prompt.tags || []),
    ]
      .join(' ')
      .toLowerCase();
    if (haystack.includes(query)) {
      filtered.push(prompt.id);
    }
  });
  state.filteredIds = filtered;
}

function renderPrompts() {
  if (!elements.promptsList) return;
  elements.promptsList.innerHTML = '';
  if (!state.filteredIds.length) {
    elements.promptsList.innerHTML = '<p>Aucun prompt disponible pour cette recherche.</p>';
    return;
  }
  const fragment = document.createDocumentFragment();
  const grouped = new Map();
  state.filteredIds.forEach((id) => {
    const prompt = state.promptsIndex.get(id);
    if (!prompt) return;
    const family = prompt.family;
    if (!grouped.has(family)) {
      grouped.set(family, []);
    }
    grouped.get(family).push(prompt);
  });
  grouped.forEach((prompts, family) => {
    const section = document.createElement('section');
    section.className = 'prompt-group';
    const header = document.createElement('h3');
    header.textContent = prompts[0].familyLabel || family;
    section.appendChild(header);
    prompts.forEach((prompt) => {
      section.appendChild(renderPromptCard(prompt));
    });
    fragment.appendChild(section);
  });
  elements.promptsList.appendChild(fragment);
}

function renderPromptCard(prompt) {
  const card = document.createElement('article');
  card.className = 'prompt-card';
  const header = document.createElement('div');
  header.className = 'prompt-card__header';
  const title = document.createElement('span');
  title.className = 'prompt-card__title';
  title.textContent = prompt.title;
  const family = document.createElement('span');
  family.className = 'prompt-card__family';
  family.textContent = prompt.familyLabel || '';
  header.appendChild(title);
  header.appendChild(family);

  const tags = document.createElement('div');
  tags.className = 'prompt-card__tags';
  (prompt.tags || []).forEach((tag) => {
    const badge = document.createElement('span');
    badge.className = 'prompt-card__tag';
    badge.textContent = tag;
    tags.appendChild(badge);
  });

  const meta = document.createElement('p');
  meta.textContent = `Budget conseillé : ${prompt.budget_profile} · Lecture : ${prompt.reading_level}`;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'primary';
  button.textContent = 'Ajouter';
  button.dataset.action = 'add-prompt';
  button.dataset.id = prompt.id;

  card.appendChild(header);
  card.appendChild(tags);
  card.appendChild(meta);
  card.appendChild(button);
  return card;
}

function addPrompt(id) {
  if (!id || state.selected.find((item) => item.id === id)) {
    return;
  }
  const prompt = state.promptsIndex.get(id);
  if (!prompt) {
    setStatus('Prompt introuvable.');
    return;
  }
  state.selected.push({ id, prompt });
  filterPrompts();
  renderPrompts();
  renderSelected();
  updateCoverage();
  updateChargeIndicator();
}

function removePrompt(id) {
  const index = state.selected.findIndex((item) => item.id === id);
  if (index >= 0) {
    state.selected.splice(index, 1);
    filterPrompts();
    renderPrompts();
    renderSelected();
    updateCoverage();
    updateChargeIndicator();
  }
}

function clearSelection() {
  state.selected = [];
  renderSelected();
  filterPrompts();
  renderPrompts();
  updateCoverage();
  updateChargeIndicator();
}

function renderSelected() {
  if (!elements.selectedList) return;
  elements.selectedList.innerHTML = '';
  state.selected.forEach((item) => {
    const li = document.createElement('li');
    const title = document.createElement('div');
    title.textContent = state.promptsIndex.get(item.id)?.title || item.id;
    li.appendChild(title);
    const meta = document.createElement('div');
    const prompt = state.promptsIndex.get(item.id);
    if (prompt) {
      meta.textContent = `${prompt.familyLabel || prompt.family} — budget ${prompt.budget_profile}`;
      li.appendChild(meta);
    }
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ghost';
    btn.dataset.action = 'remove-prompt';
    btn.dataset.id = item.id;
    btn.textContent = 'Retirer';
    li.appendChild(btn);
    elements.selectedList.appendChild(li);
  });
}

function parseArtefacts() {
  if (!state.rawArtefacts.trim()) {
    state.artefacts = {};
    setStatus('Aucun artefact importé.');
    updateCoverage();
    return;
  }
  try {
    const data = JSON.parse(state.rawArtefacts);
    if (typeof data !== 'object' || Array.isArray(data)) {
      throw new Error('Format inattendu');
    }
    state.artefacts = data;
    setStatus('Artefacts importés.');
    fetchSuggestions();
    updateCoverage();
  } catch (error) {
    console.error(error);
    setStatus('Impossible de lire les artefacts (JSON invalide).');
  }
}

async function updateCoverage() {
  if (!state.selected.length) {
    state.coverage = { scores: {}, alerts: [] };
    renderCoverage();
    renderAlerts();
    return;
  }
  try {
    const body = {
      artefacts: state.artefacts,
      selected_prompts: state.selected.map((item) => item.id),
    };
    const data = await jsonPost('/api/journal-critique/coverage', body);
    state.coverage = data.coverage || { scores: {}, alerts: [] };
    renderCoverage();
    renderAlerts();
    fetchRecommendationsFromCoverage();
  } catch (error) {
    console.error(error);
    setStatus('Erreur lors de l’évaluation de la couverture.');
  }
}

function renderCoverage() {
  if (!elements.coverage) return;
  elements.coverage.innerHTML = '';
  const scores = state.coverage.scores || {};
  DOMAINS.forEach((domain) => {
    const dt = document.createElement('dt');
    dt.textContent = domain.charAt(0).toUpperCase() + domain.slice(1);
    const dd = document.createElement('dd');
    const value = typeof scores[domain] === 'number' ? scores[domain] : 0;
    const progress = document.createElement('progress');
    progress.max = 100;
    progress.value = value;
    progress.title = `${value}%`;
    dd.appendChild(progress);
    const span = document.createElement('span');
    span.textContent = ` ${value}%`;
    dd.appendChild(span);
    elements.coverage.appendChild(dt);
    elements.coverage.appendChild(dd);
  });
}

function renderAlerts() {
  if (!elements.alerts) return;
  elements.alerts.innerHTML = '';
  const alerts = state.coverage.alerts || [];
  alerts.forEach((alert) => {
    const li = document.createElement('li');
    li.textContent = alert;
    elements.alerts.appendChild(li);
  });
}

function fetchRecommendationsFromCoverage() {
  const alerts = state.coverage.alerts || [];
  const domains = new Set();
  alerts.forEach((alert) => {
    const match = alert.match(/domaine (\w+)/i);
    if (match) {
      domains.add(match[1].toLowerCase());
    }
  });
  domains.forEach((domain) => fetchRecommendations(domain));
}

async function fetchRecommendations(domain) {
  if (!elements.recommendations) return;
  try {
    const data = await jsonGet(`/api/journal-critique/recommendations?domain=${encodeURIComponent(domain)}`);
    const templates = Array.isArray(data?.templates) ? data.templates : [];
    state.recommendations[domain] = {
      templates,
      source: data?.source || 'inconnu',
    };
    renderRecommendations();
  } catch (error) {
    console.error(error);
    setStatus(`Recommandations ${domain} indisponibles pour le moment.`);
  }
}

function renderRecommendations() {
  if (!elements.recommendations) return;
  elements.recommendations.innerHTML = '';
  const entries = Object.entries(state.recommendations);
  if (!entries.length) {
    elements.recommendations.innerHTML = '<p>Aucune recommandation disponible.</p>';
    return;
  }
  let rendered = 0;
  entries.forEach(([domain, payload]) => {
    if (!payload || !payload.templates || !payload.templates.length) {
      return;
    }
    const wrapper = document.createElement('div');
    const title = document.createElement('h4');
    title.textContent = `${domain} (${payload.source || 'demo'})`;
    wrapper.appendChild(title);
    payload.templates.forEach((suggestion) => {
      const card = document.createElement('div');
      card.className = 'recommendation-card';
      const heading = document.createElement('h5');
      heading.textContent = suggestion.title;
      card.appendChild(heading);
      const tags = document.createElement('p');
      const tagsList = suggestion.suggested_tags || suggestion.tags || [];
      tags.textContent = `Tags suggérés : ${tagsList.length ? tagsList.join(', ') : '—'}`;
      card.appendChild(tags);
      const pre = document.createElement('pre');
      pre.textContent = suggestion.skeleton_md || suggestion.template || '';
      card.appendChild(pre);
      wrapper.appendChild(card);
    });
    elements.recommendations.appendChild(wrapper);
    rendered += 1;
  });
  if (!rendered) {
    elements.recommendations.innerHTML = '<p>Aucune recommandation supplémentaire pour le moment.</p>';
  }
}

function updateChargeIndicator() {
  if (!elements.chargeValue) return;
  if (!state.selected.length) {
    elements.chargeValue.textContent = 'aucun prompt sélectionné';
    return;
  }
  let total = 0;
  state.selected.forEach((item) => {
    const prompt = state.promptsIndex.get(item.id);
    if (!prompt) return;
    let weight = 1;
    if (prompt.budget_profile === 'moyen') weight = 1.2;
    if (prompt.budget_profile === 'eleve') weight = 1.5;
    if (state.budget === 'faible') weight += 0.2;
    total += weight;
  });
  const label = total <= 3 ? 'faible' : total <= 5 ? 'modérée' : 'élevée';
  elements.chargeValue.textContent = `${state.selected.length} invites — charge ${label}`;
}

async function fetchSuggestions() {
  if (!state.artefacts || Object.keys(state.artefacts).length === 0) {
    state.suggestions = [];
    renderSuggestions();
    setStatus('Ajoutez des artefacts Post‑séance pour obtenir des suggestions.');
    return;
  }
  try {
    const body = {
      artefacts: state.artefacts,
      budget_profile: state.budget,
    };
    const data = await jsonPost('/api/journal-critique/suggestions', body);
    state.suggestions = Array.isArray(data.suggestions) ? data.suggestions : [];
    renderSuggestions();
  } catch (error) {
    console.error(error);
    setStatus('Erreur lors de la récupération des suggestions.');
  }
}

function renderSuggestions() {
  if (!elements.suggestions) return;
  elements.suggestions.innerHTML = '';
  if (!state.suggestions.length) return;
  state.suggestions.forEach((item) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'suggestion-chip';
    const promptId = item.prompt && item.prompt.id ? item.prompt.id : item.id;
    chip.dataset.id = promptId;
    chip.dataset.action = 'add-prompt';
    const title = item.prompt && item.prompt.title ? item.prompt.title : promptId;
    chip.textContent = `${title} (${item.justification || 'pertinent'})`;
    elements.suggestions.appendChild(chip);
  });
}

async function handlePreview() {
  if (!state.selected.length) {
    setStatus('Sélectionnez au moins un prompt.');
    return;
  }
  try {
    const payload = buildPayload();
    const data = await jsonPost('/api/journal-critique/preview', payload);
    if (elements.preview && elements.previewOutput) {
      elements.preview.hidden = false;
      const base64 = data.preview?.preview_pdf_base64 || '';
      elements.previewOutput.value = base64
        ? `data:application/pdf;base64,${base64}`
        : 'Prévisualisation indisponible';
    }
    setStatus('Prévisualisation générée.');
  } catch (error) {
    console.error(error);
    setStatus(error.message || 'Prévisualisation impossible.');
  }
}

async function handleGenerate() {
  if (!state.selected.length) {
    setStatus('Sélectionnez au moins un prompt.');
    return;
  }
  try {
    setStatus('Génération du journal en cours…');
    const payload = buildPayload();
    const data = await jsonPost('/api/journal-critique/generate', payload);
    const urls = data.data || {};
    if (urls.pdf_url || urls.docx_url) {
      setStatus('Journal généré.');
      fetchHistory();
    } else {
      setStatus('Génération terminée.');
    }
  } catch (error) {
    console.error(error);
    setStatus(error.message || 'Génération impossible.');
  }
}

function buildPayload() {
  const patient = getCurrentPatient();
  return {
    patient: {
      id: patient?.id || '',
      name: patient?.displayName || '',
      gender: state.genre,
    },
    langage: state.langage,
    genre: state.genre,
    budget_profile: state.budget,
    selected_prompts: state.selected.map((item) => item.id),
    notes_praticien: state.notes,
    artefacts: state.artefacts,
    from_postsession: Boolean(state.artefacts && Object.keys(state.artefacts).length),
  };
}

function getCurrentPatient() {
  const patientId = getState('selectedPatientId');
  const patients = getState('patientsCache') || [];
  return patients.find((patient) => patient.id === patientId) || null;
}

function handlePatientChange() {
  restorePatient();
  fetchHistory();
}

function restorePatient() {
  const patient = getCurrentPatient();
  state.patientId = patient ? patient.id : null;
  state.patientName = patient ? patient.displayName : '';
  loadPreferences();
  updateRadioStates();
}

function updateRadioStates() {
  container
    .querySelectorAll('input[name="jc-langage"]')
    .forEach((input) => {
      input.checked = input.value === state.langage;
    });
  container
    .querySelectorAll('input[name="jc-genre"]')
    .forEach((input) => {
      input.checked = input.value === state.genre;
    });
  container
    .querySelectorAll('input[name="jc-budget"]')
    .forEach((input) => {
      input.checked = input.value === state.budget;
    });
}

function preferenceKey() {
  return state.patientId ? `${STORAGE_PREFIX}${state.patientId}` : null;
}

function loadPreferences() {
  const key = preferenceKey();
  if (!key) return;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return;
    const data = JSON.parse(raw);
    if (data.langage) state.langage = data.langage;
    if (data.genre) state.genre = data.genre;
    if (data.budget) state.budget = data.budget;
  } catch (error) {
    console.error(error);
  }
}

function savePreferences() {
  const key = preferenceKey();
  if (!key) return;
  const payload = {
    langage: state.langage,
    genre: state.genre,
    budget: state.budget,
  };
  try {
    localStorage.setItem(key, JSON.stringify(payload));
  } catch (error) {
    console.error(error);
  }
}

async function fetchHistory() {
  if (!elements.history) return;
  if (!state.patientId) {
    elements.history.innerHTML = '';
    return;
  }
  try {
    const data = await jsonGet(`/api/journal-critique/history?patient=${encodeURIComponent(state.patientId)}`);
    state.history = Array.isArray(data.history) ? data.history : [];
    renderHistory();
  } catch (error) {
    console.error(error);
    setStatus('Historique indisponible.');
  }
}

function renderHistory() {
  if (!elements.history) return;
  elements.history.innerHTML = '';
  state.history.forEach((item) => {
    const li = document.createElement('li');
    const date = item.timestamp || '';
    const pdf = item.pdf ? `/api/journal-critique/exports/${item.pdf}` : null;
    const docx = item.docx ? `/api/journal-critique/exports/${item.docx}` : null;
    const title = document.createElement('span');
    title.textContent = `Journal du ${date}`;
    li.appendChild(title);
    if (pdf) {
      const linkPdf = document.createElement('a');
      linkPdf.href = pdf;
      linkPdf.textContent = 'PDF';
      linkPdf.target = '_blank';
      linkPdf.rel = 'noopener';
      li.appendChild(document.createTextNode(' '));
      li.appendChild(linkPdf);
    }
    if (docx) {
      const linkDocx = document.createElement('a');
      linkDocx.href = docx;
      linkDocx.textContent = 'DOCX';
      linkDocx.target = '_blank';
      linkDocx.rel = 'noopener';
      li.appendChild(document.createTextNode(' '));
      li.appendChild(linkDocx);
    }
    elements.history.appendChild(li);
  });
}
