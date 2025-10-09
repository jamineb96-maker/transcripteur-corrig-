const LOG_PREFIX = "[anatomy3d]";
const STORAGE_PREFIX = "anatomy3d";
const STORAGE_KEYS = {
  mode: "anatomy3d_mode",
  annotations: `${STORAGE_PREFIX}.annotations`,
  snapshots: `${STORAGE_PREFIX}.snapshots`,
  telemetry: `${STORAGE_PREFIX}.stats`,
  preferences: `${STORAGE_PREFIX}.prefs`,
};
const LEGACY_MODE_KEY = `${STORAGE_PREFIX}.mode`;

const DEFAULT_STATE = {
  mode: "global",
  highContrast: false,
  laserPointer: false,
  lowPowerMode: false,
  sceneId: null,
  scenes: [],
  layers: [],
  glossary: [],
  synonyms: [],
  annotations: [],
  snapshots: [],
  sequences: [],
  glossaryMap: new Map(),
  synonymsMap: new Map(),
  stats: {
    opened: 0,
    sceneSelections: 0,
    captures: 0,
  },
};

function safeParse(json, fallback) {
  if (!json) {
    return fallback;
  }
  try {
    return JSON.parse(json);
  } catch (error) {
    console.warn(LOG_PREFIX, "parse error", error);
    return fallback;
  }
}

function persist(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    console.warn(LOG_PREFIX, "persist error", error);
  }
}

export function createStateStore(options = {}) {
  const listeners = new Set();
  const storedAnnotations = safeParse(localStorage.getItem(STORAGE_KEYS.annotations), []);
  const storedSnapshots = safeParse(localStorage.getItem(STORAGE_KEYS.snapshots), []);
  const storedPrefs = safeParse(localStorage.getItem(STORAGE_KEYS.preferences), {});
  const storedStats = safeParse(localStorage.getItem(STORAGE_KEYS.telemetry), DEFAULT_STATE.stats);

  function syncGlobalModePreference() {
    try {
      localStorage.setItem(STORAGE_KEYS.mode, DEFAULT_STATE.mode);
      localStorage.removeItem(LEGACY_MODE_KEY);
    } catch (error) {
      console.warn(LOG_PREFIX, "persist error", error);
    }
  }

  syncGlobalModePreference();

  const state = {
    ...DEFAULT_STATE,
    lowPowerMode: Boolean(options.lowPowerMode),
    annotations: storedAnnotations,
    snapshots: storedSnapshots,
    stats: {
      ...DEFAULT_STATE.stats,
      ...storedStats,
    },
    ...storedPrefs,
  };

  function notify() {
    listeners.forEach(fn => fn(state));
  }

  function setMode() {
    state.mode = DEFAULT_STATE.mode;
    syncGlobalModePreference();
    notify();
  }

  function setPreferences(prefs) {
    if (typeof prefs !== "object" || !prefs) {
      return;
    }
    Object.assign(state, prefs);
    persist(STORAGE_KEYS.preferences, {
      highContrast: state.highContrast,
      laserPointer: state.laserPointer,
    });
    notify();
  }

  function setScenes(scenes) {
    state.scenes = Array.isArray(scenes) ? scenes : [];
    if (!state.sceneId && state.scenes.length > 0) {
      state.sceneId = state.scenes[0].id;
    }
    notify();
  }

  function setLayers(layers) {
    state.layers = Array.isArray(layers) ? layers : [];
    notify();
  }

  function setGlossary(entries) {
    state.glossary = Array.isArray(entries) ? entries : [];
    state.glossaryMap = new Map(state.glossary.map(entry => [entry.key, entry]));
    notify();
  }

  function setSynonyms(entries) {
    state.synonyms = Array.isArray(entries) ? entries : [];
    state.synonymsMap = new Map(state.synonyms.map(entry => [entry.key, entry.synonyms || []]));
  }

  function setSequences(entries) {
    state.sequences = Array.isArray(entries) ? entries : [];
    notify();
  }

  function selectScene(id) {
    if (!id || state.sceneId === id) {
      return;
    }
    if (!state.scenes.some(scene => scene.id === id)) {
      return;
    }
    state.sceneId = id;
    state.stats.sceneSelections += 1;
    persist(STORAGE_KEYS.telemetry, state.stats);
    notify();
  }

  function incrementOpen() {
    state.stats.opened += 1;
    persist(STORAGE_KEYS.telemetry, state.stats);
  }

  function recordCapture() {
    state.stats.captures += 1;
    persist(STORAGE_KEYS.telemetry, state.stats);
  }

  function addAnnotation(annotation) {
    state.annotations.push(annotation);
    persist(STORAGE_KEYS.annotations, state.annotations);
    notify();
  }

  function updateAnnotation(id, patch) {
    const index = state.annotations.findIndex(item => item.id === id);
    if (index === -1) {
      return;
    }
    state.annotations[index] = { ...state.annotations[index], ...patch };
    persist(STORAGE_KEYS.annotations, state.annotations);
    notify();
  }

  function deleteAnnotation(id) {
    state.annotations = state.annotations.filter(item => item.id !== id);
    persist(STORAGE_KEYS.annotations, state.annotations);
    notify();
  }

  function setAnnotations(list) {
    state.annotations = Array.isArray(list) ? list : [];
    persist(STORAGE_KEYS.annotations, state.annotations);
    notify();
  }

  function addSnapshot(snapshot) {
    state.snapshots.push(snapshot);
    persist(STORAGE_KEYS.snapshots, state.snapshots);
    notify();
  }

  function removeSnapshot(id) {
    state.snapshots = state.snapshots.filter(item => item.id !== id);
    persist(STORAGE_KEYS.snapshots, state.snapshots);
    notify();
  }

  function setSnapshots(list) {
    state.snapshots = Array.isArray(list) ? list : [];
    persist(STORAGE_KEYS.snapshots, state.snapshots);
    notify();
  }

  function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  return {
    state,
    subscribe,
    setMode,
    setPreferences,
    setScenes,
    setLayers,
    setGlossary,
    setSynonyms,
    setSequences,
    selectScene,
    addAnnotation,
    updateAnnotation,
    deleteAnnotation,
    setAnnotations,
    addSnapshot,
    removeSnapshot,
    setSnapshots,
    incrementOpen,
    recordCapture,
  };
}
