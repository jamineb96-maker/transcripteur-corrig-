const TAB_ID = 'library';
const VIEW_URL = `/static/tabs/library/index.html?v=${window.ASSET_VERSION || ''}`;
const STYLE_URL = `/static/tabs/library/style.css?v=${window.ASSET_VERSION || ''}`;

let container = null;
let initialized = false;
let pollingToken = null;

const state = {
  docId: '',
  metadata: null,
  extraction: null,
  plan: null,
  pseudonymize: true,
  prefill: null,
  effective: {},
  serverOverrides: {},
  localOverrides: {},
  prefillLoading: false,
  prefillGeneratedAt: null,
  language: '',
  silentUpdate: false,
};

const DOC_STATS_RETRY_COOLDOWN_MS = 15000;

const stateV2 = {
  docId: '',
  chunks: [],
  chunkCount: 0,
  notionCount: 0,
  notionLinks: 0,
  lastIndexMs: null,
  lastIndexInserted: 0,
  notionList: [],
  searchHits: [],
  lastStatsErrorAt: 0,
};

const refs = {};

const FIELD_LABELS = {
  title: 'Titre',
  authors: 'Auteur·ices',
  year: 'Année',
  type: 'Type',
  evidence_level: 'Niveau de preuve',
  domains: 'Domaines',
  keywords: 'Mots-clés',
  notes: 'Notes critiques',
  critical_candidates: 'Notes candidates',
  toggles: 'Activation Pré/Post',
  pseudonymize: 'Pseudonymiser',
};

const PROVENANCE_LABELS = {
  xmp: 'XMP',
  info: 'Infos PDF',
  heuristic: 'Heuristique',
  fallback: 'Défaut',
  rule: 'Règle locale',
  defaults: 'Réglage local',
  nlp_local: 'Analyse locale',
  tfidf: 'Analyse locale',
  user_override: 'Saisie manuelle',
};

function formatErrorMessage(error) {
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

function escapeHtml(value) {
  if (value === null || value === undefined) {
    return '';
  }
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function parseListInput(text) {
  if (!text) return [];
  return text
    .split(/[,;\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function valuesEqual(a, b) {
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    return a.every((item, index) => valuesEqual(item, b[index]));
  }
  if (typeof a === 'object' && a && typeof b === 'object' && b) {
    const keysA = Object.keys(a);
    const keysB = Object.keys(b);
    if (keysA.length !== keysB.length) return false;
    return keysA.every((key) => valuesEqual(a[key], b[key]));
  }
  return a === b;
}

function formatProvenance(code) {
  if (!code) return '';
  return PROVENANCE_LABELS[code] || code;
}

function createHandledError(message, cause) {
  const error = new Error(message || 'library-module-error');
  error.handled = true;
  if (cause) {
    error.cause = cause;
  }
  return error;
}

function dispatchRetry() {
  if (typeof window.requestTabReload === 'function') {
    window.requestTabReload(TAB_ID);
    return;
  }
  if (typeof window.retryTab === 'function') {
    window.retryTab(TAB_ID);
    return;
  }
  window.dispatchEvent(
    new CustomEvent('assist:retry-tab', {
      detail: { tabId: TAB_ID },
    }),
  );
}

function renderFatalError(error, context = 'Impossible de charger le module bibliothèque.') {
  if (!container) {
    return;
  }
  console.error('[tab:library] module error', error); // eslint-disable-line no-console
  container.dataset.loaded = 'false';
  const detail = formatErrorMessage(error);
  container.innerHTML = `
    <div class="tab-error" data-tab-status>
      <h3>Module bibliothèque indisponible</h3>
      <p>${context}</p>
      <p class="muted">Détails : ${detail}</p>
      <div class="tab-error__actions">
        <button type="button" class="primary" data-action="retry-tab" data-tab-id="${TAB_ID}">Réessayer</button>
      </div>
    </div>
  `;
  const retryButton = container.querySelector('[data-action="retry-tab"]');
  if (retryButton) {
    retryButton.addEventListener('click', () => {
      retryButton.disabled = true;
      retryButton.textContent = 'Nouvelle tentative…';
      dispatchRetry();
    });
  }
}

function ensureStylesheet() {
  if (!document.querySelector('link[data-library-style="true"]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = STYLE_URL;
    link.dataset.libraryStyle = 'true';
    document.head.appendChild(link);
  }
}

async function loadView() {
  if (!container) return;
  try {
    const response = await fetch(VIEW_URL, { credentials: 'same-origin' });
    if (!response.ok) {
      throw new Error(`Statut ${response.status}`);
    }
    const markup = await response.text();
    container.innerHTML = markup;
    ensureStylesheet();
    mapRefs();
    bindEvents();
    updateSummaryPanel();
    populateNotionSources();
  } catch (error) {
    renderFatalError(error, "Impossible de charger l’interface de la bibliothèque.");
    throw createHandledError('library-view-load', error);
  }
}

function mapRefs() {
  if (!container) return;
  refs.uploadForm = container.querySelector('[data-upload-form]');
  refs.uploadButton = container.querySelector('[data-action="upload"]');
  refs.uploadStatus = container.querySelector('[data-upload-status]');
  refs.extractionStatus = container.querySelector('[data-extraction-status]');
  refs.generatePlan = container.querySelector('[data-action="generate-plan"]');
  refs.keepPromptClear = container.querySelector('[data-option-keep-clear]');
  refs.planContainer = container.querySelector('[data-plan-container]');
  refs.reviewContainer = container.querySelector('[data-review-container]');
  refs.commitButton = container.querySelector('[data-action="commit-review"]');
  refs.reviewStatus = container.querySelector('[data-review-status]');
  refs.logOutput = container.querySelector('[data-log-output]');
  refs.uploadFile = container.querySelector('[data-upload-file]');
  refs.metadataTools = container.querySelector('[data-metadata-tools]');
  refs.justificationsButton = container.querySelector('[data-action="show-justifications"]');
  refs.justificationsPanel = container.querySelector('[data-justifications-panel]');
  refs.justificationsBody = container.querySelector('[data-justifications-body]');
  refs.justificationsClose = container.querySelector('[data-action="close-justifications"]');
  refs.reextractButton = container.querySelector('[data-action="reextract"]');
  refs.reextractPanel = container.querySelector('[data-reextract-panel]');
  refs.reextractForm = container.querySelector('[data-reextract-form]');
  refs.reextractFields = container.querySelector('[data-reextract-fields]');
  refs.reextractEmpty = container.querySelector('[data-reextract-empty]');
  refs.reextractClose = container.querySelector('[data-action="close-reextract"]');
  refs.reextractConfirm = container.querySelector('[data-action="confirm-reextract"]');
  refs.saveOverrides = container.querySelector('[data-action="save-overrides"]');
  refs.indexChunksButton = container.querySelector('[data-action="index-chunks"]');
  refs.indexStatus = container.querySelector('[data-index-status]');
  refs.chunkResults = container.querySelector('[data-chunk-results]');
  refs.notionPanel = container.querySelector('[data-notion-panel]');
  refs.notionForm = container.querySelector('[data-notion-form]');
  refs.notionId = container.querySelector('[data-notion-id]');
  refs.notionLabel = container.querySelector('[data-notion-label]');
  refs.notionDefinition = container.querySelector('[data-notion-definition]');
  refs.notionSynonyms = container.querySelector('[data-notion-synonyms]');
  refs.notionDomains = container.querySelector('[data-notion-domains]');
  refs.notionEvidence = container.querySelector('[data-notion-evidence]');
  refs.notionSources = container.querySelector('[data-notion-sources]');
  refs.notionCitation = container.querySelector('[data-notion-citation]');
  refs.notionStatus = container.querySelector('[data-notion-status]');
  refs.notionSubmit = container.querySelector('[data-action="save-notion"]');
  refs.notionList = container.querySelector('[data-notion-list]');
  refs.summaryChunkCount = container.querySelector('[data-summary-chunk-count]');
  refs.summaryNotionCount = container.querySelector('[data-summary-notion-count]');
  refs.summaryDocId = container.querySelector('[data-summary-doc-id]');
  refs.summaryLastIndex = container.querySelector('[data-summary-last-index]');
  refs.searchButton = container.querySelector('[data-action="open-search-debug"]');
  refs.searchModal = container.querySelector('[data-search-modal]');
  refs.searchClose = container.querySelector('[data-action="close-search-modal"]');
  refs.searchForm = container.querySelector('[data-search-form]');
  refs.searchQuery = container.querySelector('[data-search-query]');
  refs.searchDomains = container.querySelector('[data-search-domains]');
  refs.searchYear = container.querySelector('[data-search-year]');
  refs.searchEvidence = container.querySelector('[data-search-evidence]');
  refs.searchStatus = container.querySelector('[data-search-status]');
  refs.searchResults = container.querySelector('[data-search-results]');
  refs.provenanceBadges = new Map(
    Array.from(container.querySelectorAll('[data-provenance-field]')).map((badge) => [
      badge.dataset.provenanceField,
      badge,
    ]),
  );
}

function log(message) {
  if (!refs.logOutput) return;
  const now = new Date().toISOString();
  refs.logOutput.textContent = `${now} — ${message}\n${refs.logOutput.textContent}`.slice(0, 4000);
}

function setBusy(button, busy = true) {
  if (!button) return;
  button.disabled = busy;
  button.dataset.busy = busy ? 'true' : 'false';
}

function renderExtractionStatus(status, options = {}) {
  if (!refs.extractionStatus) return;
  if (!status) {
    if (options.empty) {
      refs.extractionStatus.innerHTML = '<p class="muted">Aucun document indexé.</p>';
    } else {
      refs.extractionStatus.innerHTML = '<p>Aucun traitement en cours.</p>';
    }
    return;
  }
  const { status: phase, pages, segments, error } = status;
  if (phase === 'error') {
    refs.extractionStatus.innerHTML = `<p class="error">Échec de l'extraction : ${error || 'Erreur inconnue'}.</p>`;
  } else if (phase === 'done') {
    refs.extractionStatus.innerHTML = `<p>Extraction terminée — ${pages || 0} page(s), ${segments || 0} segment(s).</p>`;
    if (refs.generatePlan) refs.generatePlan.disabled = false;
  } else if (phase === 'running') {
    refs.extractionStatus.innerHTML = '<p>Extraction en cours…</p>';
  } else if (phase === 'queued') {
    refs.extractionStatus.innerHTML = '<p>Extraction en file d’attente…</p>';
  }
}

function updatePrefillStatus(message) {
  if (refs.uploadStatus) {
    refs.uploadStatus.textContent = message || '';
  }
}

function resetLibraryV2State() {
  stateV2.docId = '';
  stateV2.chunks = [];
  stateV2.chunkCount = 0;
  stateV2.notionCount = 0;
  stateV2.notionLinks = 0;
  stateV2.lastIndexMs = null;
  stateV2.lastIndexInserted = 0;
  stateV2.notionList = [];
  stateV2.searchHits = [];
  renderChunkResults();
  renderNotionList();
  populateNotionSources();
  updateSummaryPanel();
  renderSearchResults();
  setIndexStatus('');
  setNotionStatus('');
  setSearchStatus('');
}

function updateV2Doc(docId) {
  stateV2.docId = docId || '';
  updateIndexButtonState();
  updateSummaryPanel();
  if (!stateV2.docId) {
    stateV2.chunks = [];
    stateV2.chunkCount = 0;
    stateV2.notionList = [];
    stateV2.notionCount = 0;
    stateV2.notionLinks = 0;
    stateV2.searchHits = [];
    renderChunkResults();
    renderNotionList();
    populateNotionSources();
    updateSummaryPanel();
    renderSearchResults();
  }
}

function updateIndexButtonState() {
  if (!refs.indexChunksButton) return;
  const sourcePath = state.metadata && state.metadata.source_path ? String(state.metadata.source_path).trim() : '';
  refs.indexChunksButton.disabled = !state.docId || !sourcePath;
}

function setIndexStatus(message, { error = false } = {}) {
  if (!refs.indexStatus) return;
  refs.indexStatus.textContent = message || '';
  if (error) {
    refs.indexStatus.classList.add('error');
  } else if (refs.indexStatus.classList) {
    refs.indexStatus.classList.remove('error');
  }
}

function setNotionStatus(message, { error = false } = {}) {
  if (!refs.notionStatus) return;
  refs.notionStatus.textContent = message || '';
  if (error) {
    refs.notionStatus.classList.add('error');
  } else if (refs.notionStatus && refs.notionStatus.classList) {
    refs.notionStatus.classList.remove('error');
  }
}

function setSearchStatus(message, { error = false } = {}) {
  if (!refs.searchStatus) return;
  refs.searchStatus.textContent = message || '';
  if (error) {
    refs.searchStatus.classList.add('error');
  } else if (refs.searchStatus.classList) {
    refs.searchStatus.classList.remove('error');
  }
}

function formatChunkPages(chunk) {
  const start = Number(chunk.page_start || chunk.meta?.page_start || 0);
  const end = Number(chunk.page_end || chunk.meta?.page_end || 0);
  if (!start && !end) return '';
  if (start === end) return `p. ${start}`;
  return `p. ${start}-${end}`;
}

function createNotionBadges(notions) {
  if (!Array.isArray(notions) || !notions.length) return '';
  return notions
    .map((notion) => `<span class="chunk-card__badge">${escapeHtml(notion.label || notion.id || '')}</span>`)
    .join('');
}

function renderChunkResults() {
  if (!refs.chunkResults) return;
  const container = refs.chunkResults;
  container.innerHTML = '';
  if (!state.docId) {
    container.innerHTML = '<p class="muted">Importez un document pour lancer l’indexation.</p>';
    return;
  }
  if (!stateV2.chunks.length) {
    container.innerHTML = '<p class="muted">Aucun chunk indexé pour ce document.</p>';
    populateNotionSources();
    return;
  }
  const fragment = document.createDocumentFragment();
  stateV2.chunks.forEach((chunk) => {
    const card = document.createElement('article');
    card.className = 'chunk-card';
    const title = chunk.title || state.metadata?.title || chunk.doc_id || 'Extrait';
    const pages = formatChunkPages(chunk);
    const evidence = chunk.evidence_level || state.metadata?.evidence_level || '';
    const preview = chunk.preview || chunk.text?.slice(0, 320) || '';
    const notions = createNotionBadges(chunk.notions || []);
    card.innerHTML = `
      <header>
        <span>${escapeHtml(title)}</span>
        <span class="chunk-card__meta">
          ${pages ? `<span>${escapeHtml(pages)}</span>` : ''}
          ${evidence ? `<span>${escapeHtml(evidence)}</span>` : ''}
        </span>
      </header>
      <p class="chunk-card__preview">${escapeHtml(preview)}</p>
      ${notions ? `<div class="chunk-card__notions">${notions}</div>` : ''}
    `;
    fragment.appendChild(card);
  });
  container.appendChild(fragment);
  populateNotionSources();
}

function populateNotionSources() {
  if (!refs.notionSources) return;
  const select = refs.notionSources;
  select.innerHTML = '';
  if (!stateV2.chunks.length) {
    select.disabled = true;
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Indexer des chunks pour choisir des sources.';
    select.appendChild(option);
    return;
  }
  select.disabled = false;
  stateV2.chunks.forEach((chunk) => {
    const option = document.createElement('option');
    option.value = chunk.chunk_id;
    const pages = formatChunkPages(chunk);
    const preview = (chunk.preview || chunk.text || '').replace(/\s+/g, ' ').slice(0, 200);
    option.textContent = `${pages ? `${pages} · ` : ''}${preview}`;
    select.appendChild(option);
  });
}

function renderNotionList() {
  if (!refs.notionList) return;
  const container = refs.notionList;
  container.innerHTML = '';
  if (!state.docId) {
    container.innerHTML = '<p class="muted">Sélectionnez un document pour indexer une notion.</p>';
    return;
  }
  if (!stateV2.notionList.length) {
    container.innerHTML = '<p class="muted">Aucune notion canonique indexée pour ce document.</p>';
    return;
  }
  const fragment = document.createDocumentFragment();
  stateV2.notionList.forEach((notion) => {
    const card = document.createElement('article');
    card.className = 'notion-card';
    const synonyms = (Array.isArray(notion.synonyms) && notion.synonyms.length)
      ? `<p class="notion-card__meta">Synonymes : ${escapeHtml(notion.synonyms.join(', '))}</p>`
      : '';
    const domains = (Array.isArray(notion.domains) && notion.domains.length)
      ? `<p class="notion-card__meta">Domaines : ${escapeHtml(notion.domains.join(', '))}</p>`
      : '';
    const sources = Array.isArray(notion.sources)
      ? notion.sources
          .map((source) => {
            const cite = source.citation ? escapeHtml(source.citation) : '';
            return `<li>${escapeHtml(source.doc_id || state.docId)} ${cite ? `· ${cite}` : ''}</li>`;
          })
          .join('')
      : '';
    card.innerHTML = `
      <header>
        <strong>${escapeHtml(notion.label || notion.id || '')}</strong>
        <span class="notion-card__meta">${escapeHtml(notion.evidence_level || '')}</span>
      </header>
      <p>${escapeHtml(notion.definition || '')}</p>
      ${synonyms}
      ${domains}
      ${sources ? `<ul class="notion-card__sources">${sources}</ul>` : ''}
    `;
    fragment.appendChild(card);
  });
  container.appendChild(fragment);
}

function updateSummaryPanel() {
  if (refs.summaryDocId) {
    refs.summaryDocId.textContent = state.docId || '—';
  }
  if (refs.summaryChunkCount) {
    refs.summaryChunkCount.textContent = String(stateV2.chunkCount || 0);
  }
  const notionTotal = stateV2.notionCount || stateV2.notionList.length || 0;
  if (refs.summaryNotionCount) {
    refs.summaryNotionCount.textContent = String(notionTotal);
  }
  if (refs.summaryLastIndex) {
    if (!state.docId) {
      refs.summaryLastIndex.textContent = 'Indexer un document pour activer la recherche v2.';
    } else if (!stateV2.chunkCount) {
      refs.summaryLastIndex.textContent = 'Aucun chunk indexé pour ce document.';
    } else {
      const ms = typeof stateV2.lastIndexMs === 'number' ? ` en ${stateV2.lastIndexMs} ms` : '';
      const links = stateV2.notionLinks ? `, ${stateV2.notionLinks} lien(s) de notion` : '';
      refs.summaryLastIndex.textContent = `Dernière indexation : +${stateV2.lastIndexInserted} nouveau(x), ${stateV2.chunkCount} chunks${links}${ms}.`;
    }
  }
  if (refs.searchButton) {
    refs.searchButton.disabled = !stateV2.chunkCount;
  }
  if (refs.notionSubmit) {
    refs.notionSubmit.disabled = !state.docId || !stateV2.chunkCount;
  }
}

function renderSearchResults() {
  if (!refs.searchResults) return;
  const container = refs.searchResults;
  container.innerHTML = '';
  if (!stateV2.searchHits.length) {
    container.innerHTML = '<p class="muted">Aucun résultat pour cette requête.</p>';
    return;
  }
  const fragment = document.createDocumentFragment();
  stateV2.searchHits.forEach((hit) => {
    const card = document.createElement('article');
    card.className = 'search-hit';
    const pages = hit.pages && typeof hit.pages === 'object'
      ? formatChunkPages({ page_start: hit.pages.start, page_end: hit.pages.end })
      : '';
    const notions = createNotionBadges(hit.notions || []);
    card.innerHTML = `
      <header>
        <span>${escapeHtml(hit.title || hit.doc_id || 'Extrait')}</span>
        <span class="search-hit__meta">
          ${pages ? `<span>${escapeHtml(pages)}</span>` : ''}
          ${hit.evidence_level ? `<span>${escapeHtml(hit.evidence_level)}</span>` : ''}
          ${typeof hit.score === 'number' ? `<span>score : ${hit.score.toFixed(3)}</span>` : ''}
        </span>
      </header>
      <p class="search-hit__extract">${escapeHtml(hit.extract || '')}</p>
      ${notions ? `<div class="search-hit__notions">${notions}</div>` : ''}
    `;
    fragment.appendChild(card);
  });
  container.appendChild(fragment);
}

function computeEffective(prefill = {}, overrides = {}) {
  const effective = {};
  if (prefill && typeof prefill === 'object') {
    Object.entries(prefill).forEach(([key, value]) => {
      effective[key] = value;
    });
  }
  if (overrides && typeof overrides === 'object') {
    Object.entries(overrides).forEach(([key, payload]) => {
      if (payload && typeof payload === 'object' && 'value' in payload) {
        effective[key] = {
          value: payload.value,
          provenance: 'user_override',
          updated_at: payload.updated_at,
        };
      }
    });
  }
  return effective;
}

function getServerValue(field) {
  const override = state.serverOverrides?.[field];
  if (override && typeof override === 'object' && 'value' in override) {
    return override.value;
  }
  const prefillEntry = state.prefill?.[field];
  if (prefillEntry && typeof prefillEntry === 'object' && 'value' in prefillEntry) {
    return prefillEntry.value;
  }
  if (prefillEntry !== undefined) {
    return prefillEntry;
  }
  return null;
}

function getFieldState(field) {
  if (Object.prototype.hasOwnProperty.call(state.localOverrides, field)) {
    return { value: state.localOverrides[field], provenance: 'user_override' };
  }
  const override = state.serverOverrides?.[field];
  if (override && typeof override === 'object' && 'value' in override) {
    return { value: override.value, provenance: 'user_override', raw: override };
  }
  const prefillEntry = state.prefill?.[field];
  if (prefillEntry && typeof prefillEntry === 'object' && 'value' in prefillEntry) {
    return {
      value: prefillEntry.value,
      provenance: prefillEntry.provenance || prefillEntry.source || null,
      raw: prefillEntry,
    };
  }
  if (prefillEntry !== undefined) {
    let provenance = null;
    if (field === 'keywords') provenance = 'tfidf';
    if (field === 'critical_candidates') provenance = 'nlp_local';
    if (field === 'toggles') provenance = 'defaults';
    if (field === 'pseudonymize') provenance = 'heuristic';
    return { value: prefillEntry, provenance, raw: prefillEntry };
  }
  return { value: null, provenance: null };
}

function setProvenanceBadge(field, provenance) {
  if (!refs.provenanceBadges) return;
  const badge = refs.provenanceBadges.get(field);
  if (!badge) return;
  if (!provenance) {
    badge.hidden = true;
    badge.dataset.provenance = '';
    badge.textContent = '';
    return;
  }
  badge.hidden = false;
  badge.dataset.provenance = provenance;
  badge.textContent = formatProvenance(provenance);
}

function formatListValue(value) {
  if (!value) return '';
  if (Array.isArray(value)) {
    return value.join(', ');
  }
  return String(value);
}

function formatOverrideValue(value) {
  if (Array.isArray(value)) {
    return value.join(', ');
  }
  if (value && typeof value === 'object') {
    if (Object.prototype.hasOwnProperty.call(value, 'pre') || Object.prototype.hasOwnProperty.call(value, 'post')) {
      const pre = value.pre ? 'oui' : 'non';
      const post = value.post ? 'oui' : 'non';
      return `Pré : ${pre} · Post : ${post}`;
    }
    return JSON.stringify(value);
  }
  if (typeof value === 'boolean') {
    return value ? 'Oui' : 'Non';
  }
  return value ?? '';
}

function resetPrefillState() {
  state.prefill = null;
  state.effective = {};
  state.serverOverrides = {};
  state.localOverrides = {};
  state.prefillGeneratedAt = null;
  state.language = '';
  renderPrefill();
  toggleOverrideControls();
}

function renderPrefill() {
  if (!refs.uploadForm) return;
  const form = refs.uploadForm;
  state.effective = computeEffective(state.prefill || {}, state.serverOverrides || {});
  Object.entries(state.localOverrides).forEach(([key, value]) => {
    state.effective[key] = { value, provenance: 'user_override', updated_at: new Date().toISOString() };
  });

  state.silentUpdate = true;
  try {
    const titleState = getFieldState('title');
    const titleInput = form.elements.namedItem('title');
    if (titleInput) titleInput.value = titleState.value || '';
    setProvenanceBadge('title', titleState.provenance);

    const authorsState = getFieldState('authors');
    const authorsInput = form.elements.namedItem('authors');
    if (authorsInput) authorsInput.value = formatListValue(authorsState.value);
    setProvenanceBadge('authors', authorsState.provenance);

    const yearState = getFieldState('year');
    const yearInput = form.elements.namedItem('year');
    if (yearInput) yearInput.value = yearState.value ?? '';
    setProvenanceBadge('year', yearState.provenance);

    const typeState = getFieldState('type');
    const typeSelect = form.elements.namedItem('type');
    if (typeSelect) {
      const value = typeState.value || '';
      if (value && !Array.from(typeSelect.options).some((option) => option.value === value)) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        typeSelect.appendChild(option);
      }
      typeSelect.value = value;
    }
    setProvenanceBadge('type', typeState.provenance);

    const domainsState = getFieldState('domains');
    const domainsInput = form.elements.namedItem('domains');
    if (domainsInput) domainsInput.value = formatListValue(domainsState.value);
    setProvenanceBadge('domains', domainsState.provenance);

    const keywordsState = getFieldState('keywords');
    const keywordsInput = form.elements.namedItem('keywords');
    const keywordEntries = Array.isArray(keywordsState.value) ? keywordsState.value : [];
    const keywords = keywordEntries
      .map((item) => (typeof item === 'string' ? item : item?.text))
      .filter(Boolean);
    if (keywordsInput) keywordsInput.value = formatListValue(keywords);
    setProvenanceBadge('keywords', keywordsState.provenance);

    const evidenceState = getFieldState('evidence_level');
    const evidenceSelect = form.elements.namedItem('evidence_level');
    if (evidenceSelect) {
      const value = evidenceState.value || '';
      if (value && !Array.from(evidenceSelect.options).some((option) => option.value === value)) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        evidenceSelect.appendChild(option);
      }
      evidenceSelect.value = value;
    }
    setProvenanceBadge('evidence_level', evidenceState.provenance);

    const notesState = getFieldState('notes');
    const notesInput = form.elements.namedItem('notes');
    if (notesInput) notesInput.value = notesState.value || '';
    setProvenanceBadge('notes', notesState.provenance);

    const togglesState = getFieldState('toggles');
    const preInput = form.elements.namedItem('autosuggest_pre_default');
    const postInput = form.elements.namedItem('autosuggest_post_default');
    const togglesValue = togglesState.value || {};
    if (preInput) preInput.checked = Boolean(togglesValue.pre);
    if (postInput) postInput.checked = Boolean(togglesValue.post);
    setProvenanceBadge('toggles', togglesState.provenance);

    const pseudoState = getFieldState('pseudonymize');
    const pseudoInput = form.elements.namedItem('pseudonymize');
    if (pseudoInput) pseudoInput.checked = Boolean(pseudoState.value);
    state.pseudonymize = Boolean(pseudoState.value);
    setProvenanceBadge('pseudonymize', pseudoState.provenance);
  } finally {
    state.silentUpdate = false;
  }

  if (state.prefillLoading) {
    updatePrefillStatus('Pré-remplissage en cours…');
  } else if (state.prefill) {
    const lang = state.language ? state.language.toUpperCase() : 'N/A';
    if (state.prefillGeneratedAt) {
      const generated = new Date(state.prefillGeneratedAt).toLocaleString();
      updatePrefillStatus(`Pré-remplissage (${lang}) — ${generated}`);
    } else {
      updatePrefillStatus(`Pré-remplissage (${lang})`);
    }
  }
}

function toggleOverrideControls() {
  const hasDoc = Boolean(state.docId);
  const hasPrefill = Boolean(state.prefill);
  const hasLocal = Object.keys(state.localOverrides || {}).length > 0;
  if (refs.saveOverrides) {
    refs.saveOverrides.disabled = !hasDoc || !hasLocal;
  }
  if (refs.reextractButton) {
    refs.reextractButton.disabled = !hasDoc || state.prefillLoading || hasLocal;
  }
  if (refs.justificationsButton) {
    refs.justificationsButton.disabled = !hasPrefill;
  }
}

async function loadPrefill(docId, { silent = false } = {}) {
  if (!docId) return;
  state.prefillLoading = true;
  toggleOverrideControls();
  if (!silent) updatePrefillStatus('Pré-remplissage en cours…');
  try {
    const response = await fetch(`/library/extract/${encodeURIComponent(docId)}/prefill`);
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `Statut ${response.status}`);
    }
    applyPrefillResponse(payload);
    if (!silent) updatePrefillStatus('Pré-remplissage disponible.');
  } catch (error) {
    log(`Pré-remplissage indisponible : ${error}`);
    if (!silent) updatePrefillStatus('Pré-remplissage indisponible.');
  } finally {
    state.prefillLoading = false;
    toggleOverrideControls();
  }
}

async function refreshPrefill(forceMap = {}) {
  if (!state.docId) return;
  state.prefillLoading = true;
  toggleOverrideControls();
  updatePrefillStatus('Relance du pré-remplissage…');
  try {
    const response = await fetch(`/library/extract/${encodeURIComponent(state.docId)}/prefill`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: forceMap }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `Statut ${response.status}`);
    }
    applyPrefillResponse(payload);
    updatePrefillStatus('Pré-remplissage mis à jour.');
  } catch (error) {
    log(`Erreur pré-remplissage : ${error}`);
    updatePrefillStatus('Impossible de relancer le pré-remplissage.');
  } finally {
    state.prefillLoading = false;
    toggleOverrideControls();
  }
}

function applyPrefillResponse(payload) {
  state.prefill = payload.prefill || {};
  state.serverOverrides = payload.user_overrides || {};
  state.effective = payload.effective || computeEffective(state.prefill, state.serverOverrides);
  state.prefillGeneratedAt = payload.generated_at || null;
  state.language = payload.language || '';
  state.localOverrides = {};
  renderPrefill();
  toggleOverrideControls();
  updateIndexButtonState();
}

function collectIndexMeta() {
  const form = refs.uploadForm;
  const metadata = state.metadata || {};
  const meta = {};
  if (!form) {
    meta.title = metadata.title || '';
    meta.authors = Array.isArray(metadata.authors) ? metadata.authors.join(', ') : metadata.authors || '';
    meta.year = metadata.year || null;
    meta.domains = Array.isArray(metadata.domains) ? metadata.domains : [];
    meta.keywords = Array.isArray(metadata.keywords) ? metadata.keywords : [];
    meta.evidence_level = metadata.evidence_level || '';
    meta.pseudonymize = Boolean(metadata.pseudonymize ?? state.pseudonymize);
    meta.pseudonymize_before_llm = meta.pseudonymize;
    return meta;
  }
  const titleInput = form.elements.namedItem('title');
  const authorsInput = form.elements.namedItem('authors');
  const yearInput = form.elements.namedItem('year');
  const domainsInput = form.elements.namedItem('domains');
  const keywordsInput = form.elements.namedItem('keywords');
  const evidenceInput = form.elements.namedItem('evidence_level');
  const pseudonymizeInput = form.elements.namedItem('pseudonymize');

  meta.title = (titleInput && titleInput.value.trim()) || metadata.title || '';
  const authorsRaw = (authorsInput && authorsInput.value) || (Array.isArray(metadata.authors) ? metadata.authors.join(', ') : metadata.authors || '');
  meta.authors = parseListInput(authorsRaw).join(', ');
  const yearValue = yearInput && yearInput.value ? Number(yearInput.value) : Number(metadata.year || 0);
  meta.year = Number.isFinite(yearValue) && yearValue > 0 ? yearValue : null;
  const domainsRaw = (domainsInput && domainsInput.value) || (Array.isArray(metadata.domains) ? metadata.domains.join(', ') : metadata.domains || '');
  meta.domains = parseListInput(domainsRaw);
  const keywordsRaw = (keywordsInput && keywordsInput.value) || (Array.isArray(metadata.keywords) ? metadata.keywords.join(', ') : metadata.keywords || '');
  meta.keywords = parseListInput(keywordsRaw);
  meta.evidence_level = (evidenceInput && evidenceInput.value) || metadata.evidence_level || '';
  const pseudoValue = pseudonymizeInput ? pseudonymizeInput.checked : Boolean(metadata.pseudonymize ?? state.pseudonymize);
  meta.pseudonymize = pseudoValue;
  meta.pseudonymize_before_llm = pseudoValue;
  return meta;
}

function applyIndexResponse(payload) {
  if (!payload) return;
  stateV2.chunks = Array.isArray(payload.doc_chunks) ? payload.doc_chunks : [];
  stateV2.chunkCount = Number(payload.doc_chunk_count || stateV2.chunks.length || 0);
  stateV2.lastIndexMs = typeof payload.ms === 'number' ? payload.ms : null;
  stateV2.lastIndexInserted = Number(payload.inserted || 0);
  stateV2.notionCount = Number(payload.notions_count || stateV2.notionCount || 0);
  stateV2.notionLinks = Number(payload.notion_links || stateV2.notionLinks || 0);
  renderChunkResults();
  populateNotionSources();
  updateSummaryPanel();
}

async function fetchChunksForDoc(docId, { silent = false } = {}) {
  if (!docId) {
    stateV2.chunks = [];
    stateV2.chunkCount = 0;
    renderChunkResults();
    updateSummaryPanel();
    return;
  }
  try {
    if (!silent) setIndexStatus('Chargement des chunks…');
    const url = new URL('/api/library/chunks', window.location.origin);
    url.searchParams.set('doc_id', docId);
    const response = await fetch(url, { credentials: 'same-origin' });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Statut ${response.status}`);
    }
    stateV2.chunks = Array.isArray(payload.chunks) ? payload.chunks : [];
    stateV2.chunkCount = Number(payload.total || stateV2.chunks.length || 0);
    stateV2.notionCount = Number(payload.notions_count || stateV2.notionCount || 0);
    stateV2.notionLinks = Number(payload.notion_links || stateV2.notionLinks || 0);
    renderChunkResults();
    updateSummaryPanel();
    if (!silent) {
      setIndexStatus(`Chunks chargés (${stateV2.chunkCount}).`);
    }
    await refreshDocStats(docId, { silent: true });
  } catch (error) {
    log(`Erreur chargement chunks : ${error}`);
    if (!silent) setIndexStatus('Impossible de charger les chunks.', { error: true });
  }
}

async function fetchNotionsForDoc(docId, { silent = false } = {}) {
  if (!docId) {
    stateV2.notionList = [];
    stateV2.notionCount = 0;
    renderNotionList();
    updateSummaryPanel();
    return;
  }
  try {
    const url = new URL('/api/library/notions', window.location.origin);
    url.searchParams.set('doc_id', docId);
    const response = await fetch(url, { credentials: 'same-origin' });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Statut ${response.status}`);
    }
    const items = Array.isArray(payload.items) ? payload.items : [];
    stateV2.notionList = items;
    stateV2.notionCount = Number(payload.count || items.length || 0);
    renderNotionList();
    updateSummaryPanel();
  } catch (error) {
    log(`Erreur chargement notions : ${error}`);
    if (!silent) setNotionStatus('Impossible de charger les notions.', { error: true });
  }
}

async function refreshDocStats(docId, { silent = false } = {}) {
  if (!docId) return;
  if (silent && stateV2.lastStatsErrorAt) {
    const elapsed = Date.now() - stateV2.lastStatsErrorAt;
    if (elapsed < DOC_STATS_RETRY_COOLDOWN_MS) {
      return;
    }
  }
  try {
    const response = await fetch(`/api/library/debug/doc/${encodeURIComponent(docId)}`, {
      credentials: 'same-origin',
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Statut ${response.status}`);
    }
    stateV2.chunkCount = Number(payload.chunks_indexed || stateV2.chunkCount || 0);
    stateV2.notionCount = Number(payload.notions || stateV2.notionCount || 0);
    stateV2.notionLinks = Number(payload.notion_links || stateV2.notionLinks || 0);
    stateV2.lastStatsErrorAt = 0;
    updateSummaryPanel();
  } catch (error) {
    if (silent) {
      stateV2.lastStatsErrorAt = Date.now();
      return;
    }
    log(`Erreur statut doc : ${error}`);
    setIndexStatus('Impossible de récupérer le statut du document.', { error: true });
  }
}

async function handleIndexChunks(event) {
  if (event) event.preventDefault();
  if (!state.docId) {
    setIndexStatus('Aucun document sélectionné.', { error: true });
    return;
  }
  const docPath = state.metadata?.source_path ? String(state.metadata.source_path) : '';
  if (!docPath) {
    setIndexStatus('Chemin du document introuvable.', { error: true });
    return;
  }
  const meta = collectIndexMeta();
  state.pseudonymize = Boolean(meta.pseudonymize);
  const payload = {
    doc_id: state.docId,
    doc_path: docPath,
    meta,
  };
  setIndexStatus('Indexation en cours…');
  setBusy(refs.indexChunksButton, true);
  try {
    const response = await fetch('/api/library/index_chunks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'same-origin',
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.message || data.error || `Statut ${response.status}`);
    }
    applyIndexResponse(data);
    setIndexStatus(`Indexation terminée (${stateV2.chunkCount} chunks).`);
    await fetchNotionsForDoc(state.docId, { silent: true });
    await refreshDocStats(state.docId, { silent: true });
    log(`Indexation réussie pour ${state.docId} (${data.inserted} nouveaux).`);
  } catch (error) {
    log(`Erreur indexation : ${error}`);
    setIndexStatus('Indexation impossible.', { error: true });
  } finally {
    setBusy(refs.indexChunksButton, false);
  }
}

function openSearchModal(event) {
  if (event) event.preventDefault();
  if (!refs.searchModal) return;
  if (!state.docId || !stateV2.chunkCount) {
    setSearchStatus('Indexer un document avant de tester la recherche.', { error: true });
    return;
  }
  refs.searchModal.hidden = false;
  refs.searchModal.setAttribute('aria-hidden', 'false');
  setSearchStatus('');
  renderSearchResults();
  if (refs.searchQuery) {
    requestAnimationFrame(() => refs.searchQuery && refs.searchQuery.focus());
  }
}

function closeSearchModal() {
  if (!refs.searchModal) return;
  refs.searchModal.hidden = true;
  refs.searchModal.setAttribute('aria-hidden', 'true');
}

async function handleSearchDebug(event) {
  event.preventDefault();
  if (!state.docId || !refs.searchForm) {
    setSearchStatus('Aucun document actif.', { error: true });
    return;
  }
  const query = refs.searchQuery ? refs.searchQuery.value.trim() : '';
  if (!query) {
    setSearchStatus('Saisissez une requête.', { error: true });
    return;
  }
  const filters = {};
  const domains = refs.searchDomains ? parseListInput(refs.searchDomains.value) : [];
  if (domains.length) filters.domains = domains;
  const yearValue = refs.searchYear && refs.searchYear.value ? Number(refs.searchYear.value) : null;
  if (Number.isFinite(yearValue) && yearValue) filters.min_year = yearValue;
  const evidence = refs.searchEvidence ? refs.searchEvidence.value : '';
  if (evidence) filters.min_evidence_level = evidence;

  setSearchStatus('Recherche en cours…');
  try {
    const response = await fetch('/api/library/search_debug', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, filters, k: 8 }),
      credentials: 'same-origin',
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.message || data.error || `Statut ${response.status}`);
    }
    stateV2.searchHits = Array.isArray(data.hits)
      ? data.hits
      : Array.isArray(data)
        ? data
        : [];
    renderSearchResults();
    const ms = typeof data.ms === 'number' ? `${data.ms} ms` : '—';
    setSearchStatus(`Résultats obtenus (${ms}).`);
  } catch (error) {
    log(`Erreur recherche debug : ${error}`);
    setSearchStatus('Recherche impossible.', { error: true });
  }
}

async function handleNotionSubmit(event) {
  event.preventDefault();
  if (!state.docId) {
    setNotionStatus('Aucun document sélectionné.', { error: true });
    return;
  }
  if (!refs.notionForm) return;
  const id = refs.notionId ? refs.notionId.value.trim() : '';
  const label = refs.notionLabel ? refs.notionLabel.value.trim() : '';
  const definition = refs.notionDefinition ? refs.notionDefinition.value.trim() : '';
  const chunkIds = refs.notionSources ? Array.from(refs.notionSources.selectedOptions).map((option) => option.value).filter(Boolean) : [];
  const citation = refs.notionCitation ? refs.notionCitation.value.trim() : '';
  if (!id || !label || !definition) {
    setNotionStatus('Identifiant, étiquette et définition sont requis.', { error: true });
    return;
  }
  if (!chunkIds.length) {
    setNotionStatus('Sélectionnez au moins un chunk source.', { error: true });
    return;
  }
  if (!citation) {
    setNotionStatus('Ajoutez une citation pour la source.', { error: true });
    return;
  }
  const synonyms = refs.notionSynonyms ? parseListInput(refs.notionSynonyms.value) : [];
  const domains = refs.notionDomains ? parseListInput(refs.notionDomains.value) : [];
  const evidence = refs.notionEvidence ? refs.notionEvidence.value : '';
  const payload = {
    id,
    label,
    definition,
    synonyms,
    domains,
    evidence_level: evidence,
    sources: [
      {
        doc_id: state.docId,
        chunk_ids: chunkIds,
        citation,
      },
    ],
  };
  setNotionStatus('Enregistrement en cours…');
  if (refs.notionSubmit) setBusy(refs.notionSubmit, true);
  try {
    const response = await fetch('/api/library/notions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'same-origin',
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.message || data.error || `Statut ${response.status}`);
    }
    setNotionStatus('Notion indexée.');
    if (refs.notionForm) refs.notionForm.reset();
    await fetchNotionsForDoc(state.docId, { silent: true });
    await refreshDocStats(state.docId, { silent: true });
    log(`Notion ${id} indexée pour ${state.docId}.`);
  } catch (error) {
    log(`Erreur notion : ${error}`);
    setNotionStatus('Impossible d’enregistrer la notion.', { error: true });
  } finally {
    if (refs.notionSubmit) setBusy(refs.notionSubmit, false);
  }
}

function handleFieldInput(event) {
  if (!state.docId || state.silentUpdate) return;
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement)) {
    return;
  }
  const { name } = target;
  let fieldKey = null;
  let parsedValue;

  switch (name) {
    case 'title':
      fieldKey = 'title';
      parsedValue = target.value.trim();
      break;
    case 'authors':
      fieldKey = 'authors';
      parsedValue = parseListInput(target.value);
      break;
    case 'year':
      fieldKey = 'year';
      parsedValue = target.value ? Number(target.value) : null;
      if (Number.isNaN(parsedValue)) parsedValue = null;
      break;
    case 'type':
      fieldKey = 'type';
      parsedValue = target.value || null;
      break;
    case 'domains':
      fieldKey = 'domains';
      parsedValue = parseListInput(target.value);
      break;
    case 'keywords':
      fieldKey = 'keywords';
      parsedValue = parseListInput(target.value);
      break;
    case 'evidence_level':
      fieldKey = 'evidence_level';
      parsedValue = target.value || null;
      break;
    case 'notes':
      fieldKey = 'notes';
      parsedValue = target.value.trim();
      break;
    case 'autosuggest_pre_default':
    case 'autosuggest_post_default':
      fieldKey = 'toggles';
      parsedValue = {
        pre: Boolean(refs.uploadForm.elements.namedItem('autosuggest_pre_default')?.checked),
        post: Boolean(refs.uploadForm.elements.namedItem('autosuggest_post_default')?.checked),
      };
      break;
    case 'pseudonymize':
      fieldKey = 'pseudonymize';
      parsedValue = target.checked;
      break;
    default:
      return;
  }

  const baseline = getServerValue(fieldKey);
  if (valuesEqual(parsedValue, baseline)) {
    delete state.localOverrides[fieldKey];
  } else {
    state.localOverrides[fieldKey] = parsedValue;
  }
  renderPrefill();
  toggleOverrideControls();
}

async function saveOverrides(event) {
  if (event) event.preventDefault();
  if (!state.docId || !Object.keys(state.localOverrides).length) {
    return;
  }
  if (!refs.saveOverrides) return;
  setBusy(refs.saveOverrides, true);
  const originalLabel = refs.saveOverrides.textContent;
  refs.saveOverrides.textContent = 'Enregistrement…';
  try {
    const overridesPayload = {};
    Object.entries(state.localOverrides).forEach(([key, value]) => {
      overridesPayload[key] = { value };
    });
    const response = await fetch(`/library/extract/${encodeURIComponent(state.docId)}/apply_overrides`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ overrides: overridesPayload }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `Statut ${response.status}`);
    }
    applyPrefillResponse(payload);
    updatePrefillStatus('Modifications enregistrées.');
    log('Overrides enregistrés.');
  } catch (error) {
    log(`Erreur overrides : ${error}`);
    updatePrefillStatus('Échec de l’enregistrement des modifications.');
  } finally {
    refs.saveOverrides.textContent = originalLabel || 'Enregistrer les modifications';
    setBusy(refs.saveOverrides, false);
  }
}

function renderJustifications() {
  if (!refs.justificationsBody) return;
  const prefill = state.prefill;
  if (!prefill || !Object.keys(prefill).length) {
    refs.justificationsBody.innerHTML = '<p class="muted">Aucune justification disponible.</p>';
    return;
  }
  const sections = [];
  const metaInfo = [];
  if (state.language) {
    metaInfo.push(`Langue détectée : <strong>${escapeHtml(state.language.toUpperCase())}</strong>`);
  }
  if (state.prefillGeneratedAt) {
    metaInfo.push(`Généré le ${escapeHtml(new Date(state.prefillGeneratedAt).toLocaleString())}`);
  }
  if (metaInfo.length) {
    sections.push(`<section><p>${metaInfo.join('<br />')}</p></section>`);
  }

  if (prefill.title) {
    sections.push(
      `<section><h4>${FIELD_LABELS.title}</h4><p>${escapeHtml(prefill.title.value || '')}</p><small>${escapeHtml(formatProvenance(prefill.title.provenance))}</small></section>`,
    );
  }
  if (prefill.authors) {
    const authors = Array.isArray(prefill.authors.value || prefill.authors) ? prefill.authors.value || prefill.authors : [];
    sections.push(
      `<section><h4>${FIELD_LABELS.authors}</h4><ul>${authors.map((author) => `<li>${escapeHtml(author)}</li>`).join('')}</ul></section>`,
    );
  }
  if (prefill.year) {
    sections.push(
      `<section><h4>${FIELD_LABELS.year}</h4><p>${escapeHtml(prefill.year.value ?? prefill.year)}</p><small>${escapeHtml(
        formatProvenance(prefill.year.provenance),
      )}</small></section>`,
    );
  }
  if (prefill.type) {
    const signals = Array.isArray(prefill.type.signals) && prefill.type.signals.length
      ? `<small>Signaux : ${prefill.type.signals.map((signal) => `<code>${escapeHtml(signal)}</code>`).join(', ')}</small>`
      : '';
    sections.push(
      `<section><h4>${FIELD_LABELS.type}</h4><p>${escapeHtml(prefill.type.value || '')}</p>${signals}</section>`,
    );
  }
  if (prefill.evidence_level) {
    const conflict = prefill.evidence_level.conflict ? '<small>Conflit détecté avec la règle.</small>' : '';
    sections.push(
      `<section><h4>${FIELD_LABELS.evidence_level}</h4><p>${escapeHtml(prefill.evidence_level.value || '')}</p>${conflict}</section>`,
    );
  }
  if (prefill.domains) {
    const domains = Array.isArray(prefill.domains.value || prefill.domains) ? prefill.domains.value || prefill.domains : [];
    sections.push(
      `<section><h4>${FIELD_LABELS.domains}</h4><ul>${domains.map((domain) => `<li>${escapeHtml(domain)}</li>`).join('')}</ul></section>`,
    );
  }
  const keywords = Array.isArray(prefill.keywords?.value ?? prefill.keywords)
    ? prefill.keywords.value || prefill.keywords
    : [];
  if (keywords.length) {
    sections.push(
      `<section><h4>${FIELD_LABELS.keywords}</h4><ul>${keywords
        .map((keyword) => {
          if (typeof keyword === 'string') return `<li>${escapeHtml(keyword)}</li>`;
          const source = keyword.source ? `<small>(${escapeHtml(keyword.source)})</small>` : '';
          return `<li><strong>${escapeHtml(keyword.text || '')}</strong> ${source}</li>`;
        })
        .join('')}</ul></section>`,
    );
  }
  const notesCandidates = Array.isArray(prefill.critical_candidates?.value ?? prefill.critical_candidates)
    ? prefill.critical_candidates.value || prefill.critical_candidates
    : [];
  if (notesCandidates.length) {
    sections.push(
      `<section><h4>${FIELD_LABELS.critical_candidates}</h4>${notesCandidates
        .map((note) => `<pre>${escapeHtml(note)}</pre>`)
        .join('')}</section>`,
    );
  }
  if (prefill.toggles) {
    const toggles = prefill.toggles.value || prefill.toggles;
    sections.push(
      `<section><h4>${FIELD_LABELS.toggles}</h4><p>Pré : ${toggles.pre ? 'Oui' : 'Non'} · Post : ${toggles.post ? 'Oui' : 'Non'}</p></section>`,
    );
  }
  if (prefill.pseudonymize !== undefined) {
    const pseudo = prefill.pseudonymize.value ?? prefill.pseudonymize;
    sections.push(
      `<section><h4>${FIELD_LABELS.pseudonymize}</h4><p>${pseudo ? 'Oui' : 'Non'}</p></section>`,
    );
  }
  refs.justificationsBody.innerHTML = sections.join('');
}

function openJustifications() {
  if (!refs.justificationsPanel) return;
  renderJustifications();
  refs.justificationsPanel.hidden = false;
  refs.justificationsPanel.setAttribute('aria-hidden', 'false');
}

function closeJustifications() {
  if (!refs.justificationsPanel) return;
  refs.justificationsPanel.hidden = true;
  refs.justificationsPanel.setAttribute('aria-hidden', 'true');
}

function renderReextract() {
  if (!refs.reextractFields) return;
  refs.reextractFields.innerHTML = '';
  const overrides = state.serverOverrides || {};
  const fields = Object.keys(overrides);
  if (!fields.length) {
    if (refs.reextractEmpty) refs.reextractEmpty.hidden = false;
    return;
  }
  if (refs.reextractEmpty) refs.reextractEmpty.hidden = true;
  const fragment = document.createDocumentFragment();
  fields.forEach((field) => {
    const value = overrides[field]?.value;
    const label = document.createElement('label');
    label.innerHTML = `
      <input type="checkbox" name="force" value="${field}">
      <div>
        <strong>${escapeHtml(FIELD_LABELS[field] || field)}</strong>
        <small>${escapeHtml(formatOverrideValue(value))}</small>
      </div>
    `;
    fragment.appendChild(label);
  });
  refs.reextractFields.appendChild(fragment);
}

function openReextract() {
  if (!refs.reextractPanel) return;
  renderReextract();
  refs.reextractPanel.hidden = false;
  refs.reextractPanel.setAttribute('aria-hidden', 'false');
}

function closeReextract() {
  if (!refs.reextractPanel) return;
  refs.reextractPanel.hidden = true;
  refs.reextractPanel.setAttribute('aria-hidden', 'true');
}

async function submitReextract(event) {
  event.preventDefault();
  if (!refs.reextractForm || !state.docId) return;
  const formData = new FormData(refs.reextractForm);
  const force = {};
  formData.getAll('force').forEach((field) => {
    force[field] = true;
  });
  const confirmButton = refs.reextractConfirm;
  if (confirmButton) {
    setBusy(confirmButton, true);
    const original = confirmButton.textContent;
    confirmButton.textContent = 'Relance en cours…';
    try {
      await refreshPrefill(force);
      closeReextract();
    } finally {
      confirmButton.textContent = original || 'Relancer';
      setBusy(confirmButton, false);
    }
  } else {
    await refreshPrefill(force);
    closeReextract();
  }
}

async function pollExtractionStatus(docId) {
  if (pollingToken) {
    clearTimeout(pollingToken);
  }
  if (!docId) return;
  try {
    const response = await fetch(`/library/extract/${encodeURIComponent(docId)}/status`);
    if (response.status === 404) {
      state.extraction = null;
      renderExtractionStatus(null, { empty: true });
      log('Aucun document indexé.');
      return;
    }
    if (!response.ok) throw new Error(`Statut ${response.status}`);
    const payload = await response.json();
    if (payload.ok) {
      state.extraction = payload.status;
      renderExtractionStatus(payload.status);
      if (payload.status?.status && payload.status.status !== 'done' && payload.status.status !== 'error') {
        pollingToken = setTimeout(() => pollExtractionStatus(docId), 2500);
      }
    }
  } catch (error) {
    log(`Erreur statut extraction : ${error}`);
  }
}

function collectFormData(form) {
  const data = new FormData(form);
  const json = {};
  for (const [key, value] of data.entries()) {
    if (value instanceof File) continue;
    json[key] = value;
  }
  json.pseudonymize = data.get('pseudonymize') === 'on';
  return { formData: data, meta: json };
}

async function handleUpload(event) {
  event.preventDefault();
  if (!refs.uploadForm) return;
  const { formData, meta } = collectFormData(refs.uploadForm);
  const file = formData.get('file');
  if (!(file instanceof File) || !file.size) {
    refs.uploadStatus.textContent = 'Sélectionnez un PDF.';
    return;
  }
  setBusy(refs.uploadButton, true);
  refs.uploadStatus.textContent = 'Envoi en cours…';
  try {
    const response = await fetch('/library/upload', {
      method: 'POST',
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `Statut ${response.status}`);
    }
    resetPrefillState();
    resetLibraryV2State();
    state.docId = payload.doc_id;
    state.metadata = payload.metadata;
    state.pseudonymize = Boolean(meta.pseudonymize);
    updateV2Doc(state.docId);
    updateIndexButtonState();
    refs.uploadStatus.textContent = 'Extraction initialisée.';
    log(`Document ${payload.doc_id} reçu.`);
    renderExtractionStatus(payload.status);
    if (payload.status?.status !== 'done') {
      pollExtractionStatus(payload.doc_id);
    }
    if (refs.generatePlan && payload.status?.status === 'done') {
      refs.generatePlan.disabled = false;
    }
    await loadPrefill(payload.doc_id);
    await fetchChunksForDoc(state.docId, { silent: true });
    await fetchNotionsForDoc(state.docId, { silent: true });
    await refreshDocStats(state.docId, { silent: true });
  } catch (error) {
    refs.uploadStatus.textContent = 'Erreur lors de l’envoi.';
    log(`Échec upload : ${error}`);
  } finally {
    setBusy(refs.uploadButton, false);
  }
}

function renderPlanDegraded(payload) {
  if (!refs.planContainer) return;
  const reason = payload?.reason || payload?.error || 'Sortie non conforme.';
  const parseErrors = Array.isArray(payload?.parse_errors) ? payload.parse_errors : [];
  const validatorTrace = typeof payload?.validator_trace === 'string' ? payload.validator_trace : '';
  const issues = validatorTrace
    ? validatorTrace.split('|').map((entry) => entry.trim()).filter(Boolean)
    : [];
  const preview = typeof payload?.raw_preview === 'string' ? payload.raw_preview : '';
  const schemaVersion = payload?.schema_version ? String(payload.schema_version) : '';
  const why = typeof payload?.why === 'string' && payload.why ? payload.why : '';
  const sections = [];
  if (parseErrors.length) {
    const items = parseErrors
      .map((error) => `<li>${escapeHtml(String(error))}</li>`)
      .join('');
    sections.push(`
      <div class="plan-message__section">
        <strong>Erreurs de parsing</strong>
        <ul>${items}</ul>
      </div>
    `);
  }
  if (why) {
    sections.push(`
      <div class="plan-message__section">
        <strong>Champs à corriger</strong>
        <p>${escapeHtml(why)}</p>
      </div>
    `);
  }
  if (issues.length) {
    const items = issues.map((entry) => `<li>${escapeHtml(entry)}</li>`).join('');
    sections.push(`
      <div class="plan-message__section">
        <strong>Validation</strong>
        <ul>${items}</ul>
      </div>
    `);
  }
  if (preview) {
    sections.push(`
      <div class="plan-message__section">
        <strong>Aperçu brut</strong>
        <pre class="plan-message__preview">${escapeHtml(preview)}</pre>
      </div>
    `);
  }
  const schemaLabel = schemaVersion ? `<p class="muted">Schéma attendu : ${escapeHtml(schemaVersion)}</p>` : '';
  const regenerateButton = `<div class="plan-message__actions"><button type="button" class="secondary" data-action="regenerate-strict">Régénérer avec contrainte stricte</button></div>`;
  refs.planContainer.innerHTML = `
    <article class="plan-message" data-tone="warning">
      <h3>Plan en mode dégradé</h3>
      <p>${escapeHtml(reason)}</p>
      ${schemaLabel}
      ${sections.join('')}
      ${regenerateButton}
    </article>
  `;
  const retryButton = refs.planContainer.querySelector('[data-action="regenerate-strict"]');
  if (retryButton) {
    retryButton.addEventListener('click', () => {
      void handleGeneratePlan();
    });
  }
}

function renderPlan(plan) {
  if (!refs.planContainer) return;
  refs.planContainer.innerHTML = '';
  if (!plan?.proposed_notions?.length) {
    refs.planContainer.innerHTML = '<p class="muted">Aucune notion proposée.</p>';
    return;
  }
  plan.proposed_notions.forEach((notion, index) => {
    const card = document.createElement('article');
    card.className = 'plan-card';
    card.dataset.notionIndex = String(index);
    const summary = notion.summary || '';
    const quotes = Array.isArray(notion.key_quotes) ? notion.key_quotes : [];
    const quoteList = quotes
      .map((quote) => `<li>${quote.text || ''} <span class="muted">(p. ${(quote.pages || []).join(', ')})</span></li>`)
      .join('');
    card.innerHTML = `
      <header>
        <h3>${notion.title || 'Notion sans titre'}</h3>
        <span class="badge">Priorité ${(notion.priority ?? 0).toFixed(2)}</span>
      </header>
      <p>${summary}</p>
      <div>
        <strong>Usages cliniques :</strong>
        <ul>${(notion.clinical_uses || []).map((item) => `<li>${item}</li>`).join('')}</ul>
      </div>
      <div>
        <strong>Citations clés :</strong>
        <ul>${quoteList || '<li class="muted">Aucune</li>'}</ul>
      </div>
    `;
    refs.planContainer.appendChild(card);
  });
}

function buildReviewCard(notion, index) {
  const card = document.createElement('article');
  card.className = 'review-card';
  card.dataset.notionIndex = String(index);
  const clinicalUses = (notion.clinical_uses || []).join('\n');
  const limitations = (notion.limitations_risks || []).join('\n');
  const tags = (notion.tags || []).join(', ');
  card.innerHTML = `
    <header>
      <div class="field field-inline">
        <label><input type="checkbox" data-field="include" checked /> Inclure</label>
        <span class="badge">Score ${(notion.priority ?? 0).toFixed(2)}</span>
      </div>
    </header>
    <div class="field">
      <span>Notion ID</span>
      <input type="text" data-field="notion-id" value="${notion.candidate_notion_id || ''}" />
    </div>
    <div class="field">
      <span>Titre</span>
      <input type="text" data-field="title" value="${notion.title || ''}" />
    </div>
    <div class="field">
      <span>Résumé critique</span>
      <textarea data-field="summary">${notion.summary || ''}</textarea>
    </div>
    <div class="field">
      <span>Tags canoniques</span>
      <input type="text" data-field="tags" value="${tags}" placeholder="TSA, genre" />
    </div>
    <div class="field field-inline">
      <label><input type="checkbox" data-field="autosuggest-pre" ${notion.autosuggest_pre ? 'checked' : ''}/> Pré</label>
      <label><input type="checkbox" data-field="autosuggest-post" ${notion.autosuggest_post ? 'checked' : ''}/> Post</label>
      <label>Priorité <input type="number" step="0.01" min="0" max="1" data-field="priority" value="${notion.priority ?? 0}" /></label>
    </div>
    <div class="field">
      <span>Psychoéducation</span>
      <textarea data-field="psychoeducation">${notion.summary || ''}</textarea>
    </div>
    <div class="field">
      <span>Questions d’ouverture</span>
      <textarea data-field="opening-questions">${clinicalUses}</textarea>
    </div>
    <div class="field">
      <span>Limites / risques</span>
      <textarea data-field="limitations">${limitations}</textarea>
    </div>
    <div class="field">
      <span>Rattacher à une notion existante (optionnel)</span>
      <input type="text" data-field="existing" placeholder="notion existante" />
    </div>
  `;
  card.dataset.source = JSON.stringify(notion);
  return card;
}

function renderReview(plan) {
  if (!refs.reviewContainer) return;
  refs.reviewContainer.innerHTML = '';
  if (!plan?.proposed_notions?.length) {
    refs.reviewContainer.innerHTML = '<p class="muted">Générez un plan pour préparer l’indexation.</p>';
    if (refs.commitButton) refs.commitButton.disabled = true;
    return;
  }
  plan.proposed_notions.forEach((notion, index) => {
    const card = buildReviewCard(notion, index);
    refs.reviewContainer.appendChild(card);
  });
  if (refs.commitButton) refs.commitButton.disabled = false;
}

function sanitiseList(text) {
  return text
    .split(/\r?\n|[,;]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildContribution(notion, card, original) {
  const metadata = state.metadata || {};
  const title = metadata.title || notion.title;
  const authors = Array.isArray(metadata.authors) ? metadata.authors : [];
  const citation = {
    title: title || '',
    authors,
    year: metadata.year || null,
    pages: [],
  };
  const quotes = Array.isArray(original.key_quotes) ? original.key_quotes : [];
  const evidence = original.evidence || {};
  const claims = quotes.map((quote, index) => ({
    claim_id: `${notion.notion_id || original.candidate_notion_id || 'notion'}-claim-${index + 1}`,
    text: quote.text || '',
    evidence,
    quotes: [
      {
        text: quote.text || '',
        pages: quote.pages || [],
      },
    ],
    segments: quote.segment_ids || [],
  }));
  const clinicalUses = sanitiseList(card.querySelector('[data-field="opening-questions"]').value);
  const limitations = sanitiseList(card.querySelector('[data-field="limitations"]').value);
  citation.pages = Array.from(new Set(quotes.flatMap((quote) => quote.pages || [])));
  return {
    summary: card.querySelector('[data-field="summary"]').value || original.summary || '',
    claims,
    clinical_uses: clinicalUses,
    limitations_risks: limitations,
    tags: sanitiseList(card.querySelector('[data-field="tags"]').value),
    source_citation: citation,
    key_quotes: quotes,
    notion_id: notion.notion_id,
    doc_id: state.docId,
    source_spans: original.source_spans || [],
  };
}

function collectReviewPayload() {
  if (!refs.reviewContainer) return null;
  const cards = Array.from(refs.reviewContainer.querySelectorAll('.review-card'));
  const notions = [];
  cards.forEach((card) => {
    const include = card.querySelector('[data-field="include"]').checked;
    if (!include) return;
    const original = JSON.parse(card.dataset.source || '{}');
    const notionIdInput = card.querySelector('[data-field="notion-id"]');
    const attachTo = card.querySelector('[data-field="existing"]').value.trim();
    const notionId = attachTo || notionIdInput.value.trim() || original.candidate_notion_id;
    if (!notionId) return;
    const tags = sanitiseList(card.querySelector('[data-field="tags"]').value);
    const opening = sanitiseList(card.querySelector('[data-field="opening-questions"]').value);
    const canonical = {
      notion_id: notionId,
      title: card.querySelector('[data-field="title"]').value || original.title || notionId,
      consensus_summary: card.querySelector('[data-field="summary"]').value || original.summary || '',
      canonical_tags: tags,
      priority: Number.parseFloat(card.querySelector('[data-field="priority"]').value) || 0,
      allowed_for_autosuggest_pre: card.querySelector('[data-field="autosuggest-pre"]').checked,
      allowed_for_autosuggest_post: card.querySelector('[data-field="autosuggest-post"]').checked,
      practice_guidance: {
        psychoeducation_core: card.querySelector('[data-field="psychoeducation"]').value || '',
        opening_questions_core: opening,
      },
      aliases: original.aliases || [],
      source_contributions: original.source_contributions || [],
    };
    const originalSource = JSON.parse(card.dataset.source || '{}');
    const contribution = buildContribution({ notion_id: notionId, ...canonical }, card, originalSource);
    notions.push({
      notion: canonical,
      contributions: [contribution],
    });
  });
  if (!notions.length) return null;
  return {
    doc_id: state.docId,
    notions,
  };
}

async function handleCommit() {
  if (!state.docId) {
    refs.reviewStatus.textContent = 'Aucun document chargé.';
    return;
  }
  const payload = collectReviewPayload();
  if (!payload) {
    refs.reviewStatus.textContent = 'Sélectionnez au moins une notion.';
    return;
  }
  setBusy(refs.commitButton, true);
  refs.reviewStatus.textContent = 'Indexation en cours…';
  try {
    const response = await fetch('/library/review/commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error || `Statut ${response.status}`);
    }
    refs.reviewStatus.textContent = `Notions indexées : ${result.indexed.length}`;
    log(`Indexation réussie pour ${result.indexed.length} notion(s).`);
  } catch (error) {
    refs.reviewStatus.textContent = 'Échec de l’indexation.';
    log(`Erreur indexation : ${error}`);
  } finally {
    setBusy(refs.commitButton, false);
  }
}

async function handleGeneratePlan() {
  if (!state.docId) {
    log('Aucun document pour générer un plan.');
    return;
  }
  setBusy(refs.generatePlan, true);
  refs.planContainer.innerHTML = '<p>Génération du plan…</p>';
  try {
    const response = await fetch(`/library/llm/plan/${encodeURIComponent(state.docId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pseudonymize: state.pseudonymize,
        keep_prompt_clear: refs.keepPromptClear?.checked || false,
      }),
    });
    const payload = await response.json();
    if (payload.status === 'degraded' || payload.quality === 'degraded') {
      state.plan = null;
      renderPlanDegraded(payload);
      renderReview(null);
      log(`Plan en mode dégradé : ${payload.reason || payload.error || 'sortie non conforme'}`);
      return;
    }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `Statut ${response.status}`);
    }
    state.plan = payload.plan;
    renderPlan(payload.plan);
    renderReview(payload.plan);
    log('Plan généré avec succès.');
  } catch (error) {
    refs.planContainer.innerHTML = '<p class="error">Impossible de générer le plan.</p>';
    log(`Erreur plan : ${error}`);
  } finally {
    setBusy(refs.generatePlan, false);
  }
}

function bindEvents() {
  if (!refs.uploadForm) return;
  refs.uploadForm.addEventListener('submit', handleUpload);
  refs.uploadForm.addEventListener('input', handleFieldInput, true);
  refs.uploadForm.addEventListener('change', handleFieldInput, true);
  if (refs.generatePlan) {
    refs.generatePlan.addEventListener('click', handleGeneratePlan);
  }
  if (refs.commitButton) {
    refs.commitButton.addEventListener('click', handleCommit);
  }
  if (refs.justificationsButton) {
    refs.justificationsButton.addEventListener('click', openJustifications);
  }
  if (refs.justificationsClose) {
    refs.justificationsClose.addEventListener('click', closeJustifications);
  }
  if (refs.justificationsPanel) {
    refs.justificationsPanel.addEventListener('click', (event) => {
      if (event.target === refs.justificationsPanel) {
        closeJustifications();
      }
    });
  }
  if (refs.reextractButton) {
    refs.reextractButton.addEventListener('click', openReextract);
  }
  if (refs.reextractClose) {
    refs.reextractClose.addEventListener('click', closeReextract);
  }
  if (refs.reextractPanel) {
    refs.reextractPanel.addEventListener('click', (event) => {
      if (event.target === refs.reextractPanel) {
        closeReextract();
      }
    });
  }
  if (refs.reextractForm) {
    refs.reextractForm.addEventListener('submit', submitReextract);
  }
  if (refs.saveOverrides) {
    refs.saveOverrides.addEventListener('click', saveOverrides);
  }
  if (refs.indexChunksButton) {
    refs.indexChunksButton.addEventListener('click', handleIndexChunks);
  }
  if (refs.notionForm) {
    refs.notionForm.addEventListener('submit', handleNotionSubmit);
  }
  if (refs.searchButton) {
    refs.searchButton.addEventListener('click', openSearchModal);
  }
  if (refs.searchClose) {
    refs.searchClose.addEventListener('click', closeSearchModal);
  }
  if (refs.searchModal) {
    refs.searchModal.addEventListener('click', (event) => {
      if (event.target === refs.searchModal) {
        closeSearchModal();
      }
    });
  }
  if (refs.searchForm) {
    refs.searchForm.addEventListener('submit', handleSearchDebug);
  }
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeJustifications();
      closeReextract();
      closeSearchModal();
    }
  });
  toggleOverrideControls();
}

export function init() {
  if (initialized) return;
  const tabRoot = document.querySelector('[data-tab-root]');
  if (!tabRoot) {
    console.error('[tab:library] tab root introuvable'); // eslint-disable-line no-console
    return;
  }
  try {
    container = tabRoot.querySelector(`section[data-tab="${TAB_ID}"]`);
    if (!container) {
      container = document.createElement('section');
      container.dataset.tab = TAB_ID;
      container.className = 'tab-section hidden';
      tabRoot.appendChild(container);
    }
    initialized = true;
  } catch (error) {
    console.error('[tab:library] init failed', error); // eslint-disable-line no-console
    if (!container) {
      container = document.createElement('section');
      container.dataset.tab = TAB_ID;
      container.className = 'tab-section hidden';
      tabRoot.appendChild(container);
    }
    renderFatalError(error, "Impossible d’initialiser la bibliothèque.");
    throw createHandledError('library-init', error);
  }
}

export async function show() {
  if (!initialized) {
    init();
  }
  if (!container) return;
  container.classList.remove('hidden');
  try {
    if (container.dataset.loaded !== 'true') {
      await loadView();
      container.dataset.loaded = 'true';
    }
  } catch (error) {
    if (error && error.handled) {
      throw error;
    }
    renderFatalError(error, 'Impossible d’afficher la bibliothèque.');
    throw createHandledError('library-show', error);
  }
}

export function hide() {
  if (pollingToken) {
    clearTimeout(pollingToken);
    pollingToken = null;
  }
}

export function destroy() {
  if (pollingToken) {
    clearTimeout(pollingToken);
    pollingToken = null;
  }
  resetLibraryV2State();
  if (container) {
    container.innerHTML = '';
    delete container.dataset.loaded;
  }
  Object.keys(refs).forEach((key) => {
    refs[key] = null;
  });
  container = null;
  initialized = false;
}

export default { init, show, hide, destroy };
