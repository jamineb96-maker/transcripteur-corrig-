import { jsonGet, jsonPost, jsonDelete } from '../../services/api.js';

const state = {
  entries: [],
  total: 0,
  selectedId: null,
  loading: false,
  saving: false,
};

const elements = {};

function parseList(value) {
  return (value || '')
    .split(',')
    .map((item) => item.trim())
    .filter((item, index, array) => item && array.indexOf(item) === index);
}

function parseMapping(value, keys) {
  const lines = (value || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  return lines.map((line) => {
    const [first, second] = line.split('|');
    if (keys.length === 2) {
      return { [keys[0]]: (first || '').trim(), [keys[1]]: (second || '').trim() };
    }
    return { [keys[0]]: (first || '').trim() };
  });
}

function formatDate(value) {
  if (!value) {
    return '';
  }
  try {
    const date = new Date(value);
    return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  } catch (error) {
    return value;
  }
}

function showFeedback(message, tone = 'info') {
  if (!elements.feedback) return;
  elements.feedback.textContent = message || '';
  elements.feedback.dataset.tone = tone;
  elements.feedback.hidden = !message;
}

function setLoading(isLoading) {
  state.loading = isLoading;
  if (elements.loading) {
    elements.loading.hidden = !isLoading;
  }
  if (elements.content) {
    elements.content.hidden = isLoading;
  }
}

function resetForm() {
  state.selectedId = null;
  if (!elements.form) return;
  elements.form.reset();
  elements.form.querySelector('[data-field="id"]').value = '';
  const deleteBtn = elements.form.querySelector('[data-action="delete-note"]');
  if (deleteBtn) {
    deleteBtn.disabled = true;
  }
}

function renderList() {
  if (!elements.list) {
    return;
  }

  elements.list.innerHTML = '';
  const entries = Array.isArray(state.entries) ? state.entries : [];
  if (!entries.length) {
    if (elements.emptyState) {
      elements.emptyState.hidden = false;
    }
    elements.list.setAttribute('aria-hidden', 'true');
    return;
  }

  if (elements.emptyState) {
    elements.emptyState.hidden = true;
  }
  elements.list.removeAttribute('aria-hidden');

  const list = document.createElement('ul');
  list.className = 'journal-entries__items';
  entries.forEach((item) => {
    const li = document.createElement('li');
    li.className = 'journal-entries__item';
    li.dataset.entryId = item.id;
    li.innerHTML = `
      <button type="button" data-action="select-entry" data-entry-id="${item.id}">
        <strong>${item.title || 'Sans titre'}</strong>
        <span class="journal-entries__meta">${formatDate(item.updated_at)}</span>
        <span class="journal-entries__tags">${(item.tags || []).map((tag) => `#${tag}`).join(' ')}</span>
        <span class="journal-entries__excerpt">${item.excerpt || ''}</span>
      </button>
    `;
    list.appendChild(li);
  });
  elements.list.appendChild(list);
}

function fillForm(entry) {
  if (!elements.form || !entry) return;
  elements.form.querySelector('[data-field="id"]').value = entry.id || '';
  elements.form.querySelector('[data-field="title"]').value = entry.title || '';
  elements.form.querySelector('[data-field="body_md"]').value = entry.body_md || '';
  elements.form.querySelector('[data-field="tags"]').value = (entry.tags || []).join(', ');
  elements.form.querySelector('[data-field="concepts"]').value = (entry.concepts || []).join(', ');
  elements.form.querySelector('[data-field="sources"]').value = (entry.sources || [])
    .map((item) => `${item.label || ''}|${item.url || ''}`.trim())
    .join('\n');
  elements.form.querySelector('[data-field="patients"]').value = (entry.patients || [])
    .map((item) => `${item.id || ''}|${item.name || ''}`.trim())
    .join('\n');
  const deleteBtn = elements.form.querySelector('[data-action="delete-note"]');
  if (deleteBtn) {
    deleteBtn.disabled = !entry.id;
  }
}

async function loadEntry(id) {
  if (!id) {
    resetForm();
    return;
  }
  try {
    const response = await jsonGet(`/api/journal-critique/get?id=${encodeURIComponent(id)}`);
    if (response && response.item) {
      state.selectedId = response.item.id;
      fillForm(response.item);
      showFeedback(`Note « ${response.item.title || 'Sans titre'} » chargée.`, 'info');
    }
  } catch (error) {
    console.error('journal entry load failed', error);
    showFeedback("Impossible de charger l'entrée sélectionnée.", 'error');
  }
}

async function loadEntries() {
  setLoading(true);
  try {
    const response = await jsonGet('/api/journal-critique/list?limit=200');
    state.entries = Array.isArray(response.items) ? response.items : [];
    state.total = typeof response.total === 'number' ? response.total : state.entries.length;
    renderList();
    showFeedback(state.entries.length ? '' : 'Aucune note enregistrée.', 'info');
  } catch (error) {
    console.error('journal entries list failed', error);
    showFeedback("Impossible de charger les notes.", 'error');
  } finally {
    setLoading(false);
  }
}

function collectFormData() {
  if (!elements.form) {
    return null;
  }
  const idField = elements.form.querySelector('[data-field="id"]');
  const titleField = elements.form.querySelector('[data-field="title"]');
  const bodyField = elements.form.querySelector('[data-field="body_md"]');
  const tagsField = elements.form.querySelector('[data-field="tags"]');
  const conceptsField = elements.form.querySelector('[data-field="concepts"]');
  const sourcesField = elements.form.querySelector('[data-field="sources"]');
  const patientsField = elements.form.querySelector('[data-field="patients"]');

  const payload = {
    id: idField.value.trim() || undefined,
    title: titleField.value.trim(),
    body_md: bodyField.value || '',
    tags: parseList(tagsField.value),
    concepts: parseList(conceptsField.value),
    sources: parseMapping(sourcesField.value, ['label', 'url']).filter((item) => item.label || item.url),
    patients: parseMapping(patientsField.value, ['id', 'name']).filter((item) => item.id || item.name),
  };
  return payload;
}

async function handleSubmit(event) {
  event.preventDefault();
  if (state.saving) {
    return;
  }
  const payload = collectFormData();
  if (!payload) {
    return;
  }
  if (!payload.title) {
    showFeedback('Le titre est obligatoire.', 'error');
    return;
  }
  state.saving = true;
  const submitBtn = elements.form.querySelector('[data-action="save-note"]');
  if (submitBtn) {
    submitBtn.disabled = true;
  }
  try {
    const response = await jsonPost('/api/journal-critique/save', payload);
    if (response && response.item) {
      showFeedback('Note enregistrée.', 'success');
      await loadEntries();
      await loadEntry(response.item.id);
    }
  } catch (error) {
    console.error('journal entry save failed', error);
    showFeedback("Enregistrement impossible.", 'error');
  } finally {
    state.saving = false;
    if (submitBtn) {
      submitBtn.disabled = false;
    }
  }
}

async function handleDelete() {
  const id = elements.form?.querySelector('[data-field="id"]').value;
  if (!id) {
    return;
  }
  if (!window.confirm('Supprimer cette note ?')) {
    return;
  }
  try {
    await jsonDelete(`/api/journal-critique/delete?id=${encodeURIComponent(id)}`);
    showFeedback('Note supprimée.', 'success');
    resetForm();
    await loadEntries();
  } catch (error) {
    console.error('journal entry delete failed', error);
    showFeedback('Suppression impossible.', 'error');
  }
}

async function handleReindex() {
  try {
    await jsonPost('/api/journal-critique/reindex', {});
    showFeedback('Réindexation effectuée.', 'success');
    await loadEntries();
  } catch (error) {
    console.error('journal reindex failed', error);
    showFeedback('Réindexation impossible.', 'error');
  }
}

function handleAction(event) {
  const button = event.target.closest('button[data-action]');
  if (!button) {
    return;
  }
  const action = button.dataset.action;
  if (action === 'new-note') {
    showFeedback('Nouvelle note en cours de rédaction.', 'info');
    resetForm();
    elements.form?.querySelector('[data-field="title"]').focus();
  }
  if (action === 'refresh-notes') {
    void loadEntries();
  }
  if (action === 'reindex-notes') {
    void handleReindex();
  }
  if (action === 'delete-note') {
    void handleDelete();
  }
  if (action === 'cancel-note') {
    resetForm();
    showFeedback('Édition annulée.', 'info');
  }
  if (action === 'select-entry') {
    const entryId = button.dataset.entryId;
    state.selectedId = entryId;
    void loadEntry(entryId);
  }
}

function cacheElements(root) {
  elements.root = root;
  elements.feedback = root.querySelector('[data-feedback]');
  elements.loading = root.querySelector('[data-loading]');
  elements.list = root.querySelector('[data-list]');
  elements.emptyState = root.querySelector('[data-empty]');
  elements.content = root.querySelector('[data-content]');
  elements.form = root.querySelector('[data-form]');
}

function bindEvents(root) {
  root.addEventListener('click', handleAction);
  if (elements.form) {
    elements.form.addEventListener('submit', handleSubmit);
  }
}

export function initEntriesManager(root) {
  if (!root || elements.root) {
    return;
  }
  cacheElements(root);
  bindEvents(root);
  if (elements.content) {
    elements.content.hidden = false;
  }
  resetForm();
  void loadEntries();
}

export async function reloadEntries() {
  await loadEntries();
}

