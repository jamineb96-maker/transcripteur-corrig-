import { subscribe, get as getState } from '../../services/app_state.js';
import { withAssetVersion } from '../../services/assets.js';
import { normalizeAssetUrl } from '../../services/asset_urls.js';

const MODULE_ID = 'facturation';
const VIEW_PATH = 'tabs/facturation/view.html';
const STYLE_PATH = 'tabs/facturation/style.css';
const CONTROLLER_MODULE_PATH = 'js/facturation.js';

let container;
let controller;
let unsubscribePatient;
let initialized = false;
let controllerModulePromise;

function resolveStaticAsset(path) {
  return normalizeAssetUrl(withAssetVersion(path));
}

function ensureStylesheet() {
  const id = 'facturation-tab-style';
  if (document.getElementById(id)) return;
  const link = document.createElement('link');
  link.id = id;
  link.rel = 'stylesheet';
  link.href = resolveStaticAsset(STYLE_PATH);
  document.head.appendChild(link);
}

function loadView() {
  const url = resolveStaticAsset(VIEW_PATH);
  return fetch(url)
    .then((resp) => resp.text())
    .then((html) => {
      container.innerHTML = html;
      ensureStylesheet();
    });
}

function loadControllerModule() {
  if (!controllerModulePromise) {
    const moduleUrl = resolveStaticAsset(CONTROLLER_MODULE_PATH);
    controllerModulePromise = import(/* @vite-ignore */ moduleUrl).catch((error) => {
      controllerModulePromise = undefined;
      throw error;
    });
  }
  return controllerModulePromise;
}

function applySelectedPatient(patientId) {
  if (!controller || !container) return;
  const patients = getState('patientsCache') || [];
  const patient = patients.find((p) => p.id === patientId);
  controller.setPatient(patient || null);
  controller.refresh();
}

export function init() {
  if (initialized) return;
  container = document.querySelector('section[data-tab="facturation"]');
  if (!container) return;
  loadView()
    .then(() => loadControllerModule())
    .then((mod) => {
      const factory = mod?.createFacturationController;
      if (typeof factory !== 'function') {
        throw new Error('Module facturation invalide: createFacturationController manquant');
      }
      controller = factory(container);
      controller.init();
      const currentPatient = getState('selectedPatientId');
      if (currentPatient) {
        applySelectedPatient(currentPatient);
      }
      unsubscribePatient = subscribe('selectedPatientId', (next) => {
        applySelectedPatient(next);
      });
      initialized = true;
    })
    .catch((error) => {
      console.error(`[${MODULE_ID}] chargement du module échoué`, error);
      container.innerHTML = '<p>Impossible de charger la facturation.</p>';
      initialized = false;
    });
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
  if (controller && typeof controller.destroy === 'function') {
    controller.destroy();
    controller = undefined;
  }
  initialized = false;
}
