// Gestion déterministe des patients côté client.

import { get as storageGet, set as storageSet } from './storage.js';
import { set as setState } from './app_state.js';
import { jsonGet, jsonPost } from './api.js';

const CACHE_KEY = 'patients:v1:cache';
const CACHE_TS_KEY = 'patients:v1:cache:ts';
const SOURCE_KEY = 'app:v1:patients-source';
const ROOTS_KEY = 'patients:v1:roots';
const CACHE_TTL_MS = 1000 * 60 * 30; // 30 minutes

function toCleanString(value) {
  if (typeof value === 'string') {
    return value.trim();
  }
  if (value == null) {
    return '';
  }
  return String(value).trim();
}

export function slugify(value) {
  const base = toCleanString(value)
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return base || 'patient';
}

export function normalizePatients(list) {
  if (!Array.isArray(list)) {
    return [];
  }

  return list
    .map((entry) => {
      if (!entry || typeof entry !== 'object') {
        return null;
      }
      const id = toCleanString(entry.id || entry.patientId || entry.patient_id || entry.slug);
      const email = toCleanString(entry.email);
      const displayNameRaw =
        toCleanString(entry.displayName || entry.display_name || entry.full_name || entry.name) ||
        email;
      const displayName = displayNameRaw
        .split(' ')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ')
        .trim();
      const nextId = id || slugify(displayName || email || 'patient');
      if (!nextId || !displayName) {
        return null;
      }
      const slug = slugify(entry.slug || nextId);
      return {
        ...entry,
        id: nextId,
        slug,
        displayName,
        email,
        name: displayName,
        full_name: displayName,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.displayName.localeCompare(b.displayName));
}

function applyPatients(list, preferredId, source = null, options = {}) {
  const { persist = true, fetchedAt = Date.now(), roots = [] } = options;
  const safeList = Array.isArray(list) ? list : [];
  const patientCount = safeList.length;
  const normalizedSource = source ?? null;

  if (persist) {
    storageSet(CACHE_KEY, safeList);
    storageSet(CACHE_TS_KEY, typeof fetchedAt === 'number' ? fetchedAt : Date.now());
    storageSet(SOURCE_KEY, normalizedSource);
    storageSet(ROOTS_KEY, Array.isArray(roots) ? roots : []);
  }

  setState('patientsCache', safeList);
  setState('patientsSource', normalizedSource);
  setState('patientsRoots', Array.isArray(roots) ? roots : []);

  const patientCountElement = document.querySelector('[data-patient-count]');
  if (patientCountElement) {
    patientCountElement.textContent = `Patients (${patientCount})`;
  }

  const select = document.getElementById('patientSelect');
  if (!select) {
    return;
  }
  select.innerHTML = '';
  const fragment = document.createDocumentFragment();
  safeList.forEach((patient) => {
    const option = document.createElement('option');
    option.value = patient.id;
    option.textContent = patient.displayName;
    if (patient.email) {
      option.dataset.email = patient.email;
    }
    fragment.appendChild(option);
  });
  select.appendChild(fragment);

  const stored = storageGet('app:v1:selectedPatient');
  const desired =
    (preferredId && safeList.some((patient) => patient.id === preferredId) && preferredId) ||
    (stored && safeList.some((patient) => patient.id === stored) && stored) ||
    (safeList[0] && safeList[0].id) ||
    '';

  if (desired) {
    select.value = desired;
    storageSet('app:v1:selectedPatient', desired);
    setState('selectedPatientId', desired);
  } else {
    select.value = '';
    storageSet('app:v1:selectedPatient', '');
    setState('selectedPatientId', '');
  }

  if (!select.dataset.bound) {
    select.addEventListener('change', (event) => {
      const value = event.target.value;
      storageSet('app:v1:selectedPatient', value);
      setState('selectedPatientId', value);
      window.dispatchEvent(
        new CustomEvent('patient:changed', {
          detail: { id: value },
        }),
      );
    });
    select.dataset.bound = 'true';
  }
}

export async function loadPatients(options = {}) {
  const { forceDemo = false } = options;
  const cache = storageGet(CACHE_KEY);
  const cachedSourceRaw = storageGet(SOURCE_KEY);
  const cachedRoots = storageGet(ROOTS_KEY);
  const cachedSourceNormalized =
    typeof cachedSourceRaw === 'string' ? cachedSourceRaw.toLowerCase() : null;
  const cacheTimestamp = storageGet(CACHE_TS_KEY);
  const now = Date.now();
  const invalidSource = cachedSourceNormalized !== 'archives';
  const ttlExpired =
    typeof cacheTimestamp !== 'number' || Number.isNaN(cacheTimestamp)
      ? true
      : now - cacheTimestamp > CACHE_TTL_MS;

  if (Array.isArray(cache) && cache.length && !forceDemo && !invalidSource && !ttlExpired) {
    const normalized = normalizePatients(cache);
    const source = cachedSourceRaw || 'cache';
    applyPatients(normalized, null, source, { persist: false, roots: Array.isArray(cachedRoots) ? cachedRoots : [] });
    return { list: normalized, source, error: null, roots: Array.isArray(cachedRoots) ? cachedRoots : [] };
  }

  const endpoint = forceDemo ? '/api/patients?demo=1' : '/api/patients';

  try {
    const response = await jsonGet(endpoint);
    const raw = Array.isArray(response?.items) ? response.items : response?.patients || response?.data || [];
    const normalized = normalizePatients(raw);
    const source = response?.source || response?.patients_source || 'api';
    const roots = Array.isArray(response?.roots) ? response.roots : [];
    const fetchedAt = Date.now();
    applyPatients(normalized, null, source, { fetchedAt, roots });
    return { list: normalized, source, error: null, roots };
  } catch (error) {
    console.error('[assist-cli] patients load failed', error);
    applyPatients([], null, null, { roots: [] });
    window.dispatchEvent(
      new CustomEvent('patients:load-error', {
        detail: { error },
      }),
    );
    return { list: [], source: null, error, roots: [] };
  }
}

export async function createPatient(payload) {
  const body = {
    id: payload?.id,
    displayName: payload?.displayName,
    slug: payload?.slug,
    email: payload?.email,
  };
  const response = await jsonPost('/api/patients', body);
  const raw = Array.isArray(response?.items) ? response.items : response?.patients || response?.data || [];
  const normalized = normalizePatients(raw);
  const roots = Array.isArray(response?.roots) ? response.roots : [];
  applyPatients(normalized, response?.selectedId || body.slug || body.id, response?.source || 'api', {
    roots,
  });
  return { list: normalized, source: response?.source || 'api', roots };
}

export async function refreshPatients() {
  const response = await jsonPost('/api/patients/refresh', {});
  const raw = Array.isArray(response?.items) ? response.items : response?.patients || response?.data || [];
  const normalized = normalizePatients(raw);
  const roots = Array.isArray(response?.roots) ? response.roots : [];
  applyPatients(normalized, response?.selectedId || null, response?.source || 'api', { roots });
  return { list: normalized, source: response?.source || 'api', roots };
}

export { applyPatients };

