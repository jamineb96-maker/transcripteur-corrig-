import { jsonGet, jsonPost } from '../../services/api.js';
import { get as getState } from '../../services/app_state.js';

let container;
let initialized = false;
let presetsList;
let historyList;
let statusLabel;
let patientLabel;

function renderPreset(preset) {
  const li = document.createElement('li');
  li.className = 'budget-preset';
  li.innerHTML = `
    <div>
      <strong>${preset.label || preset.id}</strong>
      <span>${preset.cost} cuillères</span>
    </div>
    <button type="button" data-action="log" data-preset="${preset.id}">Logguer</button>
  `;
  return li;
}

function renderHistoryItem(entry) {
  const li = document.createElement('li');
  li.className = 'budget-history__item';
  li.innerHTML = `
    <time>${entry.timestamp || '—'}</time>
    <span>${entry.note || 'Activité enregistrée'}</span>
    <span class="budget-history__value">${entry.budget != null ? `${entry.budget} cuillères` : ''}</span>
  `;
  return li;
}

async function fetchPresets() {
  if (!presetsList) {
    return;
  }
  presetsList.innerHTML = '<li>Chargement des tâches types…</li>';
  try {
    const response = await jsonGet('/api/budget/presets');
    const presets = Array.isArray(response?.presets) ? response.presets : [];
    if (!presets.length) {
      presetsList.innerHTML = '<li>Aucun préréglage pour le moment.</li>';
      return;
    }
    presetsList.innerHTML = '';
    presets.forEach((preset) => presetsList.appendChild(renderPreset(preset)));
  } catch (error) {
    console.error('[budget] presets failed', error);
    presetsList.innerHTML = '<li>Impossible de charger les préréglages.</li>';
  }
}

async function fetchHistory() {
  if (!historyList) {
    return;
  }
  const patientId = getState('selectedPatientId');
  if (!patientId) {
    historyList.innerHTML = '<li>Sélectionnez un patient pour afficher son historique.</li>';
    patientLabel.textContent = 'Aucun patient sélectionné';
    return;
  }
  historyList.innerHTML = '<li>Chargement de l’historique…</li>';
  patientLabel.textContent = `Patient : ${patientId}`;
  try {
    const response = await jsonGet(`/api/budget/history?patient=${encodeURIComponent(patientId)}`);
    const entries = Array.isArray(response?.entries) ? response.entries : [];
    historyList.innerHTML = '';
    if (!entries.length) {
      historyList.innerHTML = '<li>Aucune entrée enregistrée.</li>';
      return;
    }
    entries.forEach((entry) => historyList.appendChild(renderHistoryItem(entry)));
  } catch (error) {
    console.error('[budget] history failed', error);
    historyList.innerHTML = '<li>Historique indisponible.</li>';
  }
}

async function logPreset(presetId) {
  const patientId = getState('selectedPatientId');
  if (!patientId) {
    statusLabel.textContent = 'Sélectionnez un patient pour consigner une activité.';
    return;
  }
  statusLabel.textContent = 'Enregistrement en cours…';
  try {
    await jsonPost('/api/budget/history', {
      patient: patientId,
      note: `Activité : ${presetId}`,
      budget: 0,
    });
    statusLabel.textContent = 'Activité enregistrée.';
    fetchHistory();
  } catch (error) {
    console.error('[budget] log failed', error);
    statusLabel.textContent = "Impossible d'enregistrer l'activité.";
  }
}

function handleClick(event) {
  const action = event.target?.dataset?.action;
  if (action === 'refresh-presets') {
    fetchPresets();
  } else if (action === 'refresh-history') {
    fetchHistory();
  } else if (action === 'log') {
    const presetId = event.target.dataset.preset;
    logPreset(presetId);
  }
}

function buildView() {
  container.innerHTML = `
    <div class="panel budget-panel">
      <header class="budget-panel__header">
        <div>
          <h2>Budget cognitif</h2>
          <p class="budget-panel__patient" data-field="patient">Patient : —</p>
        </div>
        <div class="budget-panel__actions">
          <button type="button" class="ghost" data-action="refresh-presets">Actualiser les préréglages</button>
          <button type="button" class="ghost" data-action="refresh-history">Actualiser l’historique</button>
        </div>
      </header>
      <section class="budget-panel__content">
        <div class="budget-panel__column">
          <h3>Tâches types</h3>
          <ul data-field="presets" class="budget-presets"></ul>
        </div>
        <div class="budget-panel__column">
          <h3>Historique</h3>
          <ul data-field="history" class="budget-history"></ul>
        </div>
      </section>
      <footer class="budget-panel__footer">
        <span data-field="status" aria-live="polite"></span>
      </footer>
    </div>
  `;
  presetsList = container.querySelector('[data-field="presets"]');
  historyList = container.querySelector('[data-field="history"]');
  statusLabel = container.querySelector('[data-field="status"]');
  patientLabel = container.querySelector('[data-field="patient"]');
}

export function init() {
  if (initialized) {
    return;
  }
  container = document.querySelector('section[data-tab="budget"]');
  if (!container) {
    return;
  }
  buildView();
  container.addEventListener('click', handleClick);
  window.addEventListener('patient:changed', fetchHistory);
  initialized = true;
  fetchPresets();
  fetchHistory();
}

export function show() {
  if (!container) {
    return;
  }
  container.classList.remove('hidden');
  fetchHistory();
}

export function hide() {
  if (!container) {
    return;
  }
  container.classList.add('hidden');
}

export function destroy() {
  if (!container) {
    return;
  }
  container.removeEventListener('click', handleClick);
  window.removeEventListener('patient:changed', fetchHistory);
  initialized = false;
}
