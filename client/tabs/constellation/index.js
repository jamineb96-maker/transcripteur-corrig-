// Nouvelle orchestration de l'onglet Constellation.
// Indépendant du patient, persistance locale et overlay 3D optionnel.

const VIEW_URL = `/static/tabs/constellation/view.html?v=${window.ASSET_VERSION || ''}`;
const STYLE_URL = `/static/tabs/constellation/style.css?v=${window.ASSET_VERSION || ''}`;
const SYSTEMS_KEY = 'const:systems:list';
const CURRENT_SYSTEM_KEY = 'const:systems:current';
const SYSTEM_PREFIX = 'const:sys:';
const UNDO_PREFIX = 'const:undo:';
const REDO_PREFIX = 'const:redo:';
const JOURNAL_PREFIX = 'const:journal:';
const TOAST_DURATION = 4200;
const MAX_SNAPSHOTS = 30;
const SYSTEM_NAMES = ['Mélanie', 'Chloé'];
const THREE_OVERLAY_PATH = `/static/tabs/constellation/three_overlay.js?v=${window.ASSET_VERSION || ''}`;

let container = null;
let initialized = false;
let appInstance = null;
let destroyCallback = null;

class LZString {
  // Minimal LZ-String port (compressToUint8Array / decompressFromUint8Array).
  static compressToUint8Array(input) {
    const compressed = LZString._compress(input, 16, (value) => value);
    const length = compressed.length;
    const output = new Uint8Array(length * 2);
    for (let i = 0; i < length; i += 1) {
      const value = compressed.charCodeAt(i);
      output[i * 2] = value >>> 8;
      output[i * 2 + 1] = value & 0xff;
    }
    return output;
  }

  static decompressFromUint8Array(array) {
    if (!array) return '';
    const length = array.length / 2;
    const chars = [];
    for (let i = 0; i < length; i += 1) {
      chars.push(String.fromCharCode(array[i * 2] * 256 + array[i * 2 + 1]));
    }
    return LZString._decompress(chars.join(''), 32768, (index) => index);
  }

  static _compress(uncompressed, bitsPerChar, getCharFromInt) {
    if (uncompressed == null) return '';
    let i;
    const dictionary = new Map();
    const dictionaryToCreate = new Map();
    let c;
    let wc;
    let w = '';
    const enlargeIn = { value: 2 };
    let dictSize = 3;
    let numBits = 2;
    const data = [];
    let dataVal = 0;
    let dataPosition = 0;

    const pushData = (value) => {
      while (dataPosition >= bitsPerChar) {
        data.push(getCharFromInt(dataVal));
        dataVal = 0;
        dataPosition = 0;
      }
      dataVal <<= 1;
      dataVal |= value;
      dataPosition += 1;
    };

    for (i = 0; i < uncompressed.length; i += 1) {
      c = uncompressed.charAt(i);
      if (!dictionary.has(c)) {
        dictionary.set(c, dictSize++);
        dictionaryToCreate.set(c, true);
      }
      wc = w + c;
      if (dictionary.has(wc)) {
        w = wc;
      } else {
        let value;
        if (dictionaryToCreate.has(w)) {
          if (w.charCodeAt(0) < 256) {
            for (let j = 0; j < numBits; j += 1) {
              pushData(0);
            }
            value = w.charCodeAt(0);
            for (let j = 0; j < 8; j += 1) {
              pushData(value & 1);
              value >>= 1;
            }
          } else {
            let value2 = 1;
            for (let j = 0; j < numBits; j += 1) {
              pushData(value2 & 1);
              value2 >>= 1;
            }
            value = w.charCodeAt(0);
            for (let j = 0; j < 16; j += 1) {
              pushData(value & 1);
              value >>= 1;
            }
          }
          enlargeIn.value -= 1;
          if (enlargeIn.value === 0) {
            enlargeIn.value = 2 ** numBits;
            numBits += 1;
          }
          dictionaryToCreate.delete(w);
        } else {
          value = dictionary.get(w);
          for (let j = 0; j < numBits; j += 1) {
            pushData(value & 1);
            value >>= 1;
          }
        }
        enlargeIn.value -= 1;
        if (enlargeIn.value === 0) {
          enlargeIn.value = 2 ** numBits;
          numBits += 1;
        }
        dictionary.set(wc, dictSize++);
        w = String(c);
      }
    }

    if (w !== '') {
      if (dictionaryToCreate.has(w)) {
        let value;
        if (w.charCodeAt(0) < 256) {
          for (let j = 0; j < numBits; j += 1) {
            pushData(0);
          }
          value = w.charCodeAt(0);
          for (let j = 0; j < 8; j += 1) {
            pushData(value & 1);
            value >>= 1;
          }
        } else {
          let value2 = 1;
          for (let j = 0; j < numBits; j += 1) {
            pushData(value2 & 1);
            value2 >>= 1;
          }
          value = w.charCodeAt(0);
          for (let j = 0; j < 16; j += 1) {
            pushData(value & 1);
            value >>= 1;
          }
        }
        enlargeIn.value -= 1;
        if (enlargeIn.value === 0) {
          enlargeIn.value = 2 ** numBits;
          numBits += 1;
        }
        dictionaryToCreate.delete(w);
      } else {
        let value = dictionary.get(w);
        for (let j = 0; j < numBits; j += 1) {
          pushData(value & 1);
          value >>= 1;
        }
      }
      enlargeIn.value -= 1;
      if (enlargeIn.value === 0) {
        enlargeIn.value = 2 ** numBits;
        numBits += 1;
      }
    }

    const value = 2;
    for (let j = 0; j < numBits; j += 1) {
      pushData(value & 1);
      value >>= 1;
    }

    while (true) {
      dataVal <<= 1;
      if (dataPosition === bitsPerChar - 1) {
        data.push(getCharFromInt(dataVal));
        break;
      }
      dataPosition += 1;
    }

    return data.map((code) => String.fromCharCode(code)).join('');
  }

  static _decompress(compressed, resetValue, getNextValue) {
    if (compressed == null || compressed === '') return '';
    const dictionary = [];
    const data = {
      value: compressed.charCodeAt(0),
      position: resetValue,
      index: 1,
    };
    let enlargeIn = 4;
    let dictSize = 4;
    let numBits = 3;
    let entry = '';
    const result = [];

    const readBits = (n) => {
      let bits = 0;
      let maxpower = 2 ** n;
      let power = 1;
      while (power !== maxpower) {
        const resb = data.value & data.position;
        data.position >>= 1;
        if (data.position === 0) {
          data.position = resetValue;
          data.value = compressed.charCodeAt(data.index++);
        }
        bits |= (resb > 0 ? 1 : 0) * power;
        power *= 2;
      }
      return bits;
    };

    let bits = readBits(2);
    let c;
    switch (bits) {
      case 0:
        c = String.fromCharCode(readBits(8));
        break;
      case 1:
        c = String.fromCharCode(readBits(16));
        break;
      case 2:
        return '';
      default:
        c = '';
    }
    dictionary[3] = c;
    let w = c;
    result.push(c);

    while (true) {
      if (data.index > compressed.length) {
        return result.join('');
      }
      const cc = readBits(numBits);
      let code;
      if (cc === 0) {
        dictionary[dictSize++] = String.fromCharCode(readBits(8));
        code = dictSize - 1;
        enlargeIn -= 1;
      } else if (cc === 1) {
        dictionary[dictSize++] = String.fromCharCode(readBits(16));
        code = dictSize - 1;
        enlargeIn -= 1;
      } else if (cc === 2) {
        return result.join('');
      } else {
        code = cc;
      }

      if (enlargeIn === 0) {
        enlargeIn = 2 ** numBits;
        numBits += 1;
      }

      if (dictionary[code]) {
        entry = dictionary[code];
      } else if (code === dictSize) {
        entry = w + w.charAt(0);
      } else {
        return '';
      }
      result.push(entry);
      dictionary[dictSize++] = w + entry.charAt(0);
      enlargeIn -= 1;
      w = entry;
      if (enlargeIn === 0) {
        enlargeIn = 2 ** numBits;
        numBits += 1;
      }
    }
  }
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function arrayToBase64(uint8Array) {
  let binary = '';
  for (let i = 0; i < uint8Array.length; i += 1) {
    binary += String.fromCharCode(uint8Array[i]);
  }
  return btoa(binary);
}

function base64ToArray(base64) {
  const binary = atob(base64);
  const len = binary.length;
  const array = new Uint8Array(len);
  for (let i = 0; i < len; i += 1) {
    array[i] = binary.charCodeAt(i);
  }
  return array;
}

const DEFAULT_STATE = Object.freeze({
  version: 2,
  nodes: [],
  links: [],
  styles: {
    palette: 'auto',
    labelSize: 14,
    linkOpacity: 0.5,
    grid: true,
  },
  meta: {
    lastEdited: new Date().toISOString(),
    notes: '',
  },
});

function cloneDefaultState() {
  return JSON.parse(JSON.stringify(DEFAULT_STATE));
}

function deepClone(value) {
  if (typeof structuredClone === 'function') {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value));
}

function cloneSvgWithInlineStyles(svg) {
  if (!svg) return null;
  const clone = svg.cloneNode(true);
  const styleProps = ['fill', 'stroke', 'stroke-width', 'font-family', 'font-size', 'opacity'];
  const stack = [{ source: svg, target: clone }];
  while (stack.length) {
    const { source, target } = stack.pop();
    const computed = window.getComputedStyle(source);
    styleProps.forEach((prop) => {
      const value = computed.getPropertyValue(prop);
      if (value) {
        target.setAttribute(prop, value);
      }
    });
    const children = Array.from(source.children);
    children.forEach((child, index) => {
      stack.push({ source: child, target: target.children[index] });
    });
  }
  return clone;
}

function safeParse(json) {
  if (!json) return null;
  try {
    return JSON.parse(json);
  } catch (error) {
    console.warn('constellation: parse error', error);
    return null;
  }
}

function readStorage(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    console.error('constellation: storage read error', error);
    return null;
  }
}

function writeStorage(key, value) {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch (error) {
    console.error('constellation: storage write error', error);
    return false;
  }
}

function removeStorage(key) {
  try {
    localStorage.removeItem(key);
  } catch (error) {
    console.error('constellation: storage remove error', error);
  }
}

function detectBaseKey() {
  if (window.Constellation && typeof window.Constellation.storageBaseKey === 'string') {
    return window.Constellation.storageBaseKey;
  }
  const preferred = 'constellation:base';
  const legacy = [];
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (!key) continue;
      if (key.startsWith('const:')) continue;
      if (/constellation/i.test(key)) {
        legacy.push(key);
      }
    }
  } catch (error) {
    console.error('constellation: detect base key failed', error);
  }
  return legacy[0] || preferred;
}

function validateNode(node) {
  if (!node || typeof node !== 'object') return false;
  const keysOk = typeof node.id === 'string' && Number.isFinite(node.x) && Number.isFinite(node.y);
  const radiusOk = typeof node.r === 'number' && Number.isFinite(node.r);
  const notesOk = node.notes === undefined || typeof node.notes === 'string';
  return keysOk && radiusOk && notesOk;
}

function validateLink(link) {
  if (!link || typeof link !== 'object') return false;
  return typeof link.id === 'string' && typeof link.source === 'string' && typeof link.target === 'string';
}

function validateStyles(styles) {
  if (!styles || typeof styles !== 'object') return false;
  const paletteOk = ['auto', 'deutan', 'protan', 'tritan', 'high-contrast'].includes(styles.palette);
  const labelSizeOk = typeof styles.labelSize === 'number';
  const linkOpacityOk = typeof styles.linkOpacity === 'number';
  const gridOk = typeof styles.grid === 'boolean';
  return paletteOk && labelSizeOk && linkOpacityOk && gridOk;
}

function validateMeta(meta) {
  if (!meta || typeof meta !== 'object') return false;
  const dateValid = typeof meta.lastEdited === 'string';
  return dateValid && typeof meta.notes === 'string';
}

function validateSystem(data) {
  if (!data || typeof data !== 'object') return false;
  if (Number(data.version) !== 2) return false;
  if (!Array.isArray(data.nodes) || !data.nodes.every(validateNode)) return false;
  if (!Array.isArray(data.links) || !data.links.every(validateLink)) return false;
  if (!validateStyles(data.styles)) return false;
  if (!validateMeta(data.meta)) return false;
  return true;
}

function migrateLegacy(raw) {
  if (!raw) return cloneDefaultState();
  if (raw.version === 2 && validateSystem(raw)) {
    return raw;
  }
  const migrated = cloneDefaultState();
  if (Array.isArray(raw.nodes)) {
    migrated.nodes = raw.nodes
      .filter((node) => typeof node.id === 'string')
      .map((node, index) => ({
        id: node.id || `legacy-node-${index}`,
        x: Number(node.x) || 0,
        y: Number(node.y) || 0,
        r: Number(node.r) || 32,
        label: typeof node.label === 'string' ? node.label : node.id || `Nœud ${index + 1}`,
        color: node.color || '#6c63ff',
        group: node.group ?? null,
        pinned: Boolean(node.pinned),
        notes: typeof node.notes === 'string' ? node.notes : '',
      }));
  }
  if (Array.isArray(raw.links)) {
    migrated.links = raw.links
      .filter((link) => link && typeof link.source === 'string' && typeof link.target === 'string')
      .map((link, index) => ({
        id: link.id || `legacy-link-${index}`,
        source: link.source,
        target: link.target,
        kind: typeof link.kind === 'string' ? link.kind : 'relation',
        weight: Number.isFinite(link.weight) ? Number(link.weight) : 1,
      }));
  }
  if (raw.styles && typeof raw.styles === 'object') {
    migrated.styles = {
      palette: ['auto', 'deutan', 'protan', 'tritan', 'high-contrast'].includes(raw.styles.palette)
        ? raw.styles.palette
        : 'auto',
      labelSize: Number.isFinite(raw.styles.labelSize) ? Number(raw.styles.labelSize) : 14,
      linkOpacity: Number.isFinite(raw.styles.linkOpacity) ? Number(raw.styles.linkOpacity) : 0.5,
      grid: Boolean(raw.styles.grid ?? true),
    };
  }
  migrated.meta = {
    lastEdited: new Date().toISOString(),
    notes: typeof raw.meta?.notes === 'string' ? raw.meta.notes : '',
  };
  return migrated;
}

function ensureSystemRecord(name) {
  const key = `${SYSTEM_PREFIX}${name}`;
  const raw = safeParse(readStorage(key));
  if (validateSystem(raw)) {
    return raw;
  }
  const baseKey = detectBaseKey();
  const baseRaw = safeParse(readStorage(baseKey));
  const migrated = migrateLegacy(raw || baseRaw);
  migrated.version = 2;
  migrated.meta.lastEdited = migrated.meta.lastEdited || new Date().toISOString();
  writeStorage(key, JSON.stringify(migrated));
  return migrated;
}

function ensureSystems() {
  const listRaw = safeParse(readStorage(SYSTEMS_KEY));
  const list = Array.isArray(listRaw) && listRaw.length ? listRaw : [...SYSTEM_NAMES];
  writeStorage(SYSTEMS_KEY, JSON.stringify(SYSTEM_NAMES));
  const systems = {};
  list.forEach((name) => {
    systems[name] = ensureSystemRecord(name);
  });
  let current = readStorage(CURRENT_SYSTEM_KEY);
  if (!SYSTEM_NAMES.includes(current)) {
    current = SYSTEM_NAMES[0];
    writeStorage(CURRENT_SYSTEM_KEY, current);
  }
  return { systems, current };
}

class EventBus {
  constructor() {
    this.listeners = new Map();
  }

  on(event, handler) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event).add(handler);
    return () => this.off(event, handler);
  }

  off(event, handler) {
    const set = this.listeners.get(event);
    if (set) {
      set.delete(handler);
    }
  }

  emit(event, payload) {
    const set = this.listeners.get(event);
    if (!set) return;
    set.forEach((handler) => {
      try {
        handler(payload);
      } catch (error) {
        console.error('constellation: bus listener failed', error);
      }
    });
  }
}

class ConstellationApp {
  constructor(root) {
    this.root = root;
    this.toolbar = root.querySelector('#constToolbar');
    this.tabs = root.querySelector('#constSystemTabs');
    this.viewport2d = root.querySelector('#const2d');
    this.viewport3d = root.querySelector('#const3d');
    this.side = root.querySelector('#constSide');
    this.toast = root.querySelector('[data-role="toast"]');
    this.statusLabel = root.querySelector('[data-role="status"]');
    this.nodePanel = root.querySelector('[data-panel="node"]');
    this.nodeForm = this.nodePanel?.querySelector('[data-role="node-form"]');
    this.nodeEmpty = this.nodePanel?.querySelector('[data-role="node-empty"]');
    this.stylesPanel = root.querySelector('[data-panel="styles"]');
    this.stylesForm = this.stylesPanel?.querySelector('form');
    this.journalList = root.querySelector('[data-role="journal"]');
    this.snapshotsList = root.querySelector('[data-role="snapshots"]');
    this.menusRoot = root.querySelector('.const-dropdowns');
    this.bus = new EventBus();
    this.data = ensureSystems();
    this.currentSystem = this.data.current;
    this.currentState = deepClone(this.data.systems[this.currentSystem]);
    this.baseKey = detectBaseKey();
    this.pendingSave = null;
    this.pendingSaveReason = null;
    this.rafToken = null;
    this.overlay3d = null;
    this.resizeObserver = null;
    this.selectedNodeId = null;
    this.snapshotCounter = 0;
    this.modals = new Map();
    this.handleExternalSelect = (event) => {
      const detail = event?.detail;
      const nodeId = typeof detail === 'string' ? detail : detail?.id;
      if (typeof nodeId === 'string') {
        this.toggleNodeSelection(nodeId);
      }
    };
    this.toastTimeout = null;
    this.pendingRealtimeSync = null;
  }

  init() {
    this.applyStyles();
    this.mountTabs();
    this.attachToolbar();
    this.attachPanels();
    this.bindShortcuts();
    this.updateStatus(`Système « ${this.currentSystem} » prêt.`);
    this.applyThemeFromStyles();
    this.alignBaseKey();
    this.reload2D();
    this.applyDensity();
    this.populateJournal();
    this.populateSnapshots();
    this.observeResize();
    window.addEventListener('constellation:select', this.handleExternalSelect);
    this.bus.emit('system:ready', {
      name: this.currentSystem,
      state: this.currentState,
    });
    if (this.is3DEnabled()) {
      void this.enable3D();
    }
  }

  applyStyles() {
    if (!this.root) return;
    this.root.dataset.palette = this.currentState.styles.palette || 'auto';
    this.root.dataset.grid = String(Boolean(this.currentState.styles.grid));
  }

  applyThemeFromStyles() {
    this.applyStyles();
    if (!this.stylesForm) return;
    const { styles } = this.currentState;
    const paletteField = this.stylesForm.elements.namedItem('palette');
    const labelSizeField = this.stylesForm.elements.namedItem('labelSize');
    const linkOpacityField = this.stylesForm.elements.namedItem('linkOpacity');
    const gridField = this.stylesForm.elements.namedItem('grid');
    if (paletteField instanceof HTMLSelectElement) {
      paletteField.value = styles.palette;
    }
    if (labelSizeField instanceof HTMLInputElement) {
      labelSizeField.value = String(styles.labelSize);
    }
    if (linkOpacityField instanceof HTMLInputElement) {
      linkOpacityField.value = String(styles.linkOpacity);
    }
    if (gridField instanceof HTMLInputElement) {
      gridField.checked = Boolean(styles.grid);
    }
  }

  updateStatus(message) {
    if (this.statusLabel) {
      this.statusLabel.textContent = message;
    }
  }

  showToast(message, tone = 'info') {
    if (!this.toast) return;
    this.toast.textContent = message;
    this.toast.dataset.visible = 'true';
    this.toast.dataset.tone = tone;
    clearTimeout(this.toastTimeout);
    this.toastTimeout = setTimeout(() => {
      if (this.toast) {
        this.toast.dataset.visible = 'false';
      }
    }, TOAST_DURATION);
  }

  mountTabs() {
    if (!this.tabs) return;
    const buttons = Array.from(this.tabs.querySelectorAll('button[role="tab"]'));
    buttons.forEach((button) => {
      const system = button.dataset.system;
      const isActive = system === this.currentSystem;
      button.setAttribute('aria-selected', isActive ? 'true' : 'false');
      if (isActive) {
        button.tabIndex = 0;
      } else {
        button.tabIndex = -1;
      }
    });
    this.tabs.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const tab = target.closest('button[role="tab"]');
      if (!tab) return;
      const system = tab.dataset.system;
      if (!SYSTEM_NAMES.includes(system)) return;
      this.switchSystem(system);
    });
    this.tabs.addEventListener('keydown', (event) => {
      const buttonsList = Array.from(
        this.tabs.querySelectorAll('button[role="tab"]'),
      ).filter((btn) => SYSTEM_NAMES.includes(btn.dataset.system));
      const currentIndex = buttonsList.findIndex((btn) => btn.dataset.system === this.currentSystem);
      if (currentIndex < 0) return;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
        event.preventDefault();
        const next = buttonsList[(currentIndex + buttonsList.length - 1) % buttonsList.length];
        next.focus();
        this.switchSystem(next.dataset.system);
      } else if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
        event.preventDefault();
        const next = buttonsList[(currentIndex + 1) % buttonsList.length];
        next.focus();
        this.switchSystem(next.dataset.system);
      }
    });
  }

  attachToolbar() {
    if (!this.toolbar) return;
    const toggle3d = this.toolbar.querySelector('input[data-action="toggle-3d"]');
    if (toggle3d) {
      toggle3d.checked = this.is3DEnabled();
      toggle3d.addEventListener('change', (event) => {
        if (event.target.checked) {
          writeStorage('const:3d:on', '1');
          void this.enable3D();
        } else {
          writeStorage('const:3d:on', '0');
          this.disable3D();
        }
      });
    }

    this.toolbar.querySelectorAll('[data-menu]').forEach((button) => {
      button.addEventListener('click', () => {
        const menuId = button.dataset.menu;
        const currentlyExpanded = button.getAttribute('aria-expanded') === 'true';
        this.closeMenus();
        if (!currentlyExpanded) {
          button.setAttribute('aria-expanded', 'true');
          this.openMenu(menuId, button);
        }
      });
    });

    document.addEventListener('click', (event) => {
      if (!(event.target instanceof Node)) return;
      if (!this.root.contains(event.target)) {
        this.closeMenus();
      }
    });

    this.root.addEventListener('click', (event) => {
      const trigger = event.target.closest('[data-action]');
      if (!trigger) return;
      const action = trigger.dataset.action;
      switch (action) {
        case 'toggle-panel':
          this.togglePanel(trigger.dataset.panel);
          break;
        case 'close-panel':
          this.togglePanel(trigger.closest('[data-panel]')?.dataset.panel, false);
          break;
        case 'delete-node':
          this.deleteSelectedNode();
          break;
        case 'toggle-grid':
          this.toggleGrid();
          break;
        case 'set-label-size':
          this.updateStyle('labelSize', Number(trigger.value));
          break;
        case 'set-link-opacity':
          this.updateStyle('linkOpacity', Number(trigger.value));
          break;
        case 'set-palette':
          this.updateStyle('palette', trigger.value);
          break;
        case 'undo':
          this.undo();
          break;
        case 'redo':
          this.redo();
          break;
        case 'snapshot':
          this.snapshot();
          break;
        case 'import-json':
          this.importJSON();
          break;
        case 'export-json':
          this.exportJSON();
          break;
        case 'export-png':
          this.exportPNG();
          break;
        case 'export-svg':
          this.exportSVG();
          break;
        default:
      }
    });

    this.root.querySelectorAll('.const-menu input[type="range"]').forEach((input) => {
      input.addEventListener('input', (event) => {
        const { action } = event.target.dataset;
        if (action === 'set-label-size') {
          this.updateStyle('labelSize', Number(event.target.value));
        } else if (action === 'set-link-opacity') {
          this.updateStyle('linkOpacity', Number(event.target.value));
        }
      });
    });

    if (this.stylesForm) {
      this.stylesForm.addEventListener('input', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
        const { name, type } = target;
        let value;
        if (type === 'checkbox') {
          value = target.checked;
        } else if (type === 'range' || type === 'number') {
          value = Number(target.value);
        } else {
          value = target.value;
        }
        this.updateStyle(name, value);
      });
    }

    if (this.nodeForm) {
      this.nodeForm.addEventListener('submit', (event) => {
        event.preventDefault();
        this.persistNodeForm();
      });
      this.nodeForm.addEventListener('input', () => {
        this.scheduleSave('node-edit');
      });
    }
  }

  closeMenus() {
    if (!this.toolbar || !this.root) return;
    this.toolbar.querySelectorAll('[data-menu]').forEach((button) => {
      button.setAttribute('aria-expanded', 'false');
    });
    if (this.menusRoot) {
      this.menusRoot.querySelectorAll('.const-menu').forEach((menu) => {
        menu.removeAttribute('data-open');
        menu.style.removeProperty('left');
        menu.style.removeProperty('top');
      });
    }
  }

  openMenu(id, anchor) {
    if (!this.menusRoot) return;
    const menu = this.menusRoot.querySelector(`.const-menu[data-menu="${id}"]`);
    if (!menu) return;
    const rect = anchor.getBoundingClientRect();
    menu.style.left = `${rect.left}px`;
    menu.style.top = `${rect.bottom + 6}px`;
    menu.dataset.open = 'true';
    if (id === 'display') {
      menu.querySelector('[data-action="set-label-size"]').value = String(this.currentState.styles.labelSize);
      menu.querySelector('[data-action="set-link-opacity"]').value = String(this.currentState.styles.linkOpacity);
      menu.querySelector('[data-action="set-palette"]').value = this.currentState.styles.palette;
    }
  }

  togglePanel(panelName, force) {
    if (!panelName) return;
    const panel = this.root.querySelector(`[data-panel="${panelName}"]`);
    if (!panel) return;
    const shouldOpen = typeof force === 'boolean' ? force : panel.hasAttribute('hidden');
    panel.toggleAttribute('hidden', !shouldOpen);
  }

  alignBaseKey() {
    const key = this.baseKey;
    if (!key) return;
    const success = writeStorage(key, JSON.stringify(this.currentState));
    if (!success) {
      this.showToast('Impossible de synchroniser le moteur 2D. Exportez vos données puis nettoyez le stockage.', 'error');
    }
  }

  reload2D() {
    try {
      if (window.Constellation?.reload) {
        window.Constellation.reload();
      } else {
        window.dispatchEvent(new Event('storage'));
      }
    } catch (error) {
      console.error('constellation: reload failed', error);
    }
  }

  switchSystem(next) {
    if (next === this.currentSystem) return;
    this.snapshot('auto');
    this.persistSystem(this.currentSystem, this.currentState);
    this.currentSystem = next;
    writeStorage(CURRENT_SYSTEM_KEY, next);
    this.currentState = ensureSystemRecord(next);
    this.applyThemeFromStyles();
    this.applyStyles();
    this.selectedNodeId = null;
    this.renderNodeForm(null);
    this.snapshotCounter = 0;
    this.alignBaseKey();
    this.reload2D();
    this.applyDensity();
    this.populateJournal();
    this.populateSnapshots();
    this.updateStatus(`Système « ${next} » chargé.`);
    if (this.tabs) {
      this.tabs.querySelectorAll('button[role="tab"]').forEach((button) => {
        const selected = button.dataset.system === next;
        button.setAttribute('aria-selected', selected ? 'true' : 'false');
        button.tabIndex = selected ? 0 : -1;
      });
    }
    this.bus.emit('system:change', { name: next, state: this.currentState });
    if (this.overlay3d) {
      this.overlay3d.updateFrom2D(this.currentState.nodes);
    }
  }

  persistSystem(name, state) {
    const key = `${SYSTEM_PREFIX}${name}`;
    writeStorage(key, JSON.stringify(state));
  }

  scheduleSave(reason) {
    this.pendingSaveReason = reason;
    if (this.rafToken) {
      cancelAnimationFrame(this.rafToken);
    }
    this.rafToken = requestAnimationFrame(() => {
      this.rafToken = null;
      clearTimeout(this.pendingSave);
      this.pendingSave = setTimeout(() => {
        this.currentState.meta.lastEdited = new Date().toISOString();
        this.persistSystem(this.currentSystem, this.currentState);
        this.alignBaseKey();
        this.reload2D();
        this.pendingSave = null;
        this.bus.emit('system:update', {
          name: this.currentSystem,
          reason: this.pendingSaveReason,
          state: this.currentState,
        });
      }, 100);
    });
  }

  queueRealtimeSync() {
    if (this.pendingRealtimeSync) {
      return;
    }
    this.pendingRealtimeSync = requestAnimationFrame(() => {
      this.pendingRealtimeSync = null;
      this.alignBaseKey();
      this.reload2D();
    });
  }

  applyDensity() {
    if (!this.root) return;
    const dense = Array.isArray(this.currentState.nodes) && this.currentState.nodes.length > 80;
    this.root.dataset.density = dense ? 'dense' : 'normal';
  }

  toggleGrid() {
    this.updateStyle('grid', !this.currentState.styles.grid);
  }

  updateStyle(key, value) {
    if (!this.currentState.styles) {
      this.currentState.styles = { ...DEFAULT_STATE.styles };
    }
    if (key === 'palette') {
      const allowed = ['auto', 'deutan', 'protan', 'tritan', 'high-contrast'];
      if (!allowed.includes(value)) {
        return;
      }
    }
    if (key === 'linkOpacity') {
      value = Math.max(0, Math.min(1, Number(value)));
    }
    if (key === 'labelSize') {
      value = Math.max(10, Math.min(24, Number(value)));
    }
    this.currentState.styles[key] = value;
    this.applyStyles();
    this.scheduleSave('style-change');
    if (key === 'grid' && this.overlay3d) {
      this.overlay3d.setGrid(Boolean(value));
    }
  }

  persistNodeForm() {
    if (!this.nodeForm || !this.selectedNodeId) return;
    const formData = new FormData(this.nodeForm);
    const node = this.currentState.nodes.find((item) => item.id === this.selectedNodeId);
    if (!node) return;
    node.label = formData.get('label')?.toString() || node.label;
    node.group = formData.get('group')?.toString() || null;
    node.color = formData.get('color')?.toString() || node.color;
    node.pinned = formData.get('pinned') === 'on';
    node.notes = formData.get('notes')?.toString() || '';
    this.scheduleSave('node-form');
    this.showToast(`Nœud « ${node.label} » mis à jour.`);
    this.addJournalEntry({ action: 'node:update', node: node.id });
    if (this.overlay3d) {
      this.overlay3d.updateFrom2D(this.currentState.nodes);
    }
  }

  deleteSelectedNode() {
    if (!this.selectedNodeId) return;
    const index = this.currentState.nodes.findIndex((node) => node.id === this.selectedNodeId);
    if (index === -1) return;
    const [removed] = this.currentState.nodes.splice(index, 1);
    this.currentState.links = this.currentState.links.filter(
      (link) => link.source !== removed.id && link.target !== removed.id,
    );
    this.snapshot('delete-node');
    this.scheduleSave('delete-node');
    this.addJournalEntry({ action: 'node:delete', node: removed.id });
    this.selectedNodeId = null;
    this.renderNodeForm(null);
    this.showToast(`Nœud « ${removed.label} » supprimé.`);
    if (this.overlay3d) {
      this.overlay3d.updateFrom2D(this.currentState.nodes);
    }
  }

  renderNodeForm(node) {
    if (!this.nodeForm || !this.nodeEmpty) return;
    if (!node) {
      this.nodeForm.classList.add('hidden');
      this.nodeEmpty.classList.remove('hidden');
      return;
    }
    this.nodeEmpty.classList.add('hidden');
    this.nodeForm.classList.remove('hidden');
    const idField = this.nodeForm.elements.namedItem('id');
    const labelField = this.nodeForm.elements.namedItem('label');
    const groupField = this.nodeForm.elements.namedItem('group');
    const colorField = this.nodeForm.elements.namedItem('color');
    const pinnedField = this.nodeForm.elements.namedItem('pinned');
    const notesField = this.nodeForm.elements.namedItem('notes');
    if (idField instanceof HTMLInputElement) idField.value = node.id;
    if (labelField instanceof HTMLInputElement) labelField.value = node.label || '';
    if (groupField instanceof HTMLInputElement) groupField.value = node.group || '';
    if (colorField instanceof HTMLInputElement) colorField.value = node.color || '#6c63ff';
    if (pinnedField instanceof HTMLInputElement) pinnedField.checked = Boolean(node.pinned);
    if (notesField instanceof HTMLTextAreaElement) notesField.value = node.notes || '';
  }

  attachPanels() {
    this.togglePanel('node', true);
    this.togglePanel('styles', true);
    this.togglePanel('journal', true);
  }

  bindShortcuts() {
    this.keyHandler = (event) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
        return;
      }
      if (event.ctrlKey && !event.shiftKey && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        this.undo();
      } else if ((event.ctrlKey && event.key.toLowerCase() === 'y') || (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'z')) {
        event.preventDefault();
        this.redo();
      } else if (!event.ctrlKey && event.key.toLowerCase() === 'g') {
        event.preventDefault();
        this.toggleGrid();
      } else if (!event.ctrlKey && event.key.toLowerCase() === 'l') {
        event.preventDefault();
        this.toggleDensityHighlight();
      } else if (!event.ctrlKey && event.key.toLowerCase() === 's') {
        event.preventDefault();
        this.snapshot();
      } else if (!event.ctrlKey && event.key.toLowerCase() === 'e') {
        event.preventDefault();
        this.exportJSON();
      }
    };
    document.addEventListener('keydown', this.keyHandler);
  }

  toggleDensityHighlight() {
    const dense = this.root.dataset.density === 'dense';
    if (!dense) return;
    const highlight = this.root.dataset.highlightLabels === 'true';
    this.root.dataset.highlightLabels = highlight ? 'false' : 'true';
  }

  populateJournal() {
    if (!this.journalList) return;
    const journal = this.getJournal();
    this.journalList.innerHTML = '';
    journal.forEach((item) => {
      const li = document.createElement('li');
      li.textContent = `${item.t} – ${item.action}${item.node ? ` (${item.node})` : ''}`;
      this.journalList.appendChild(li);
    });
  }

  getJournal() {
    const key = `${JOURNAL_PREFIX}${this.currentSystem}`;
    const raw = safeParse(readStorage(key));
    return Array.isArray(raw) ? raw : [];
  }

  addJournalEntry(entry) {
    const key = `${JOURNAL_PREFIX}${this.currentSystem}`;
    const journal = this.getJournal();
    journal.unshift({
      t: new Date().toISOString(),
      ...entry,
    });
    if (journal.length > 50) {
      journal.length = 50;
    }
    writeStorage(key, JSON.stringify(journal));
    this.populateJournal();
  }

  encodeSnapshot() {
    const json = JSON.stringify(this.currentState);
    const compressed = LZString.compressToUint8Array(json);
    return arrayToBase64(compressed);
  }

  decodeSnapshot(raw) {
    if (!raw) return null;
    try {
      const bytes = base64ToArray(raw);
      const json = LZString.decompressFromUint8Array(bytes);
      return JSON.parse(json);
    } catch (error) {
      console.error('constellation: snapshot decode failed', error);
      return null;
    }
  }

  pushSnapshot(stackKey, data) {
    const stack = safeParse(readStorage(stackKey)) || [];
    stack.unshift(data);
    if (stack.length > MAX_SNAPSHOTS) {
      stack.length = MAX_SNAPSHOTS;
    }
    writeStorage(stackKey, JSON.stringify(stack));
  }

  popSnapshot(stackKey) {
    const stack = safeParse(readStorage(stackKey)) || [];
    const item = stack.shift();
    writeStorage(stackKey, JSON.stringify(stack));
    return item;
  }

  clearStack(stackKey) {
    writeStorage(stackKey, JSON.stringify([]));
  }

  snapshot(tag = 'manual') {
    const encoded = this.encodeSnapshot();
    const undoKey = `${UNDO_PREFIX}${this.currentSystem}`;
    const nextIndex = this.snapshotCounter + 1;
    let label = `${tag} #${nextIndex}`;
    if (tag === 'manual') {
      const userLabel = window.prompt('Nom du snapshot ?', `Snapshot ${nextIndex}`);
      if (userLabel && userLabel.trim()) {
        label = userLabel.trim();
      } else {
        label = `Snapshot ${nextIndex}`;
      }
    }
    this.snapshotCounter = nextIndex;
    this.pushSnapshot(undoKey, { tag, encoded, label, createdAt: new Date().toISOString() });
    this.clearStack(`${REDO_PREFIX}${this.currentSystem}`);
    this.addJournalEntry({ action: `snapshot:${tag}` });
    this.populateSnapshots();
  }

  undo() {
    const undoKey = `${UNDO_PREFIX}${this.currentSystem}`;
    const redoKey = `${REDO_PREFIX}${this.currentSystem}`;
    const entry = this.popSnapshot(undoKey);
    if (!entry) {
      this.showToast('Aucun état précédent.', 'warning');
      return;
    }
    this.pushSnapshot(redoKey, { tag: 'redo', encoded: this.encodeSnapshot(), createdAt: new Date().toISOString() });
    const state = this.decodeSnapshot(entry.encoded);
    if (validateSystem(state)) {
      this.currentState = state;
      this.persistSystem(this.currentSystem, this.currentState);
      this.alignBaseKey();
      this.reload2D();
      this.applyThemeFromStyles();
      this.applyDensity();
      this.populateJournal();
      this.populateSnapshots();
      this.showToast('Annulation effectuée.');
      if (this.overlay3d) {
        this.overlay3d.updateFrom2D(this.currentState.nodes);
      }
    }
  }

  redo() {
    const undoKey = `${UNDO_PREFIX}${this.currentSystem}`;
    const redoKey = `${REDO_PREFIX}${this.currentSystem}`;
    const entry = this.popSnapshot(redoKey);
    if (!entry) {
      this.showToast('Aucune action à rétablir.', 'warning');
      return;
    }
    this.pushSnapshot(undoKey, { tag: 'undo', encoded: this.encodeSnapshot(), createdAt: new Date().toISOString() });
    const state = this.decodeSnapshot(entry.encoded);
    if (validateSystem(state)) {
      this.currentState = state;
      this.persistSystem(this.currentSystem, this.currentState);
      this.alignBaseKey();
      this.reload2D();
      this.applyThemeFromStyles();
      this.applyDensity();
      this.populateJournal();
      this.populateSnapshots();
      this.showToast('Rétablissement effectué.');
      if (this.overlay3d) {
        this.overlay3d.updateFrom2D(this.currentState.nodes);
      }
    }
  }

  populateSnapshots() {
    if (!this.snapshotsList) return;
    const stack = safeParse(readStorage(`${UNDO_PREFIX}${this.currentSystem}`)) || [];
    this.snapshotCounter = stack.length;
    this.snapshotsList.innerHTML = '';
    stack.slice(0, 10).forEach((item, index) => {
      const li = document.createElement('li');
      const label = document.createElement('span');
      label.textContent = item.label || `${item.tag} ${index + 1}`;
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'Restaurer';
      button.addEventListener('click', () => {
        this.pushSnapshot(`${REDO_PREFIX}${this.currentSystem}`, {
          tag: 'redo',
          encoded: this.encodeSnapshot(),
          createdAt: new Date().toISOString(),
        });
        const state = this.decodeSnapshot(item.encoded);
        if (validateSystem(state)) {
          this.currentState = state;
          this.persistSystem(this.currentSystem, this.currentState);
          this.alignBaseKey();
          this.reload2D();
          this.applyThemeFromStyles();
          this.applyDensity();
          this.showToast(`Snapshot « ${label.textContent} » restauré.`);
        }
      });
      li.append(label, button);
      this.snapshotsList.appendChild(li);
    });
  }

  importJSON() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/json';
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const parsed = JSON.parse(String(reader.result));
          const migrated = migrateLegacy(parsed);
          if (!validateSystem(migrated)) {
            throw new Error('Schéma invalide');
          }
          this.currentState = migrated;
          this.persistSystem(this.currentSystem, this.currentState);
          this.alignBaseKey();
          this.reload2D();
          this.applyThemeFromStyles();
          this.applyDensity();
          this.addJournalEntry({ action: 'import' });
          this.showToast('Import réalisé avec succès.', 'success');
          if (this.overlay3d) {
            this.overlay3d.updateFrom2D(this.currentState.nodes);
          }
        } catch (error) {
          console.error('constellation: import failed', error);
          this.showToast('Import impossible : fichier invalide.', 'error');
        }
      };
      reader.readAsText(file);
    });
    input.click();
  }

  exportJSON() {
    const blob = new Blob([JSON.stringify(this.currentState, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    const date = new Date().toISOString().replace(/[:T]/g, '-').split('.')[0];
    link.download = `constellation_${this.currentSystem}_${date}.json`;
    link.click();
    URL.revokeObjectURL(url);
    this.addJournalEntry({ action: 'export:json' });
  }

  exportSVG() {
    const svg = this.viewport2d?.querySelector('svg');
    if (!svg) {
      this.showToast('Export SVG indisponible : aucune scène 2D détectée.', 'warning');
      return;
    }
    const clone = cloneSvgWithInlineStyles(svg) || svg.cloneNode(true);
    const serializer = new XMLSerializer();
    const markup = serializer.serializeToString(clone);
    const blob = new Blob([markup], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `constellation_${this.currentSystem}.svg`;
    link.click();
    URL.revokeObjectURL(url);
    this.addJournalEntry({ action: 'export:svg' });
    this.showToast('Export SVG lancé.', 'success');
  }

  exportPNG() {
    const svg = this.viewport2d?.querySelector('svg');
    if (!svg) {
      this.showToast('Export PNG indisponible : aucune scène 2D détectée.', 'warning');
      return;
    }
    const clone = cloneSvgWithInlineStyles(svg) || svg.cloneNode(true);
    const serializer = new XMLSerializer();
    const markup = serializer.serializeToString(clone);
    const img = new Image();
    const svgBlob = new Blob([markup], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(svgBlob);
    const viewBox = svg.viewBox?.baseVal;
    const fallbackWidth = viewBox?.width || svg.clientWidth || this.viewport2d.clientWidth || 1024;
    const fallbackHeight = viewBox?.height || svg.clientHeight || this.viewport2d.clientHeight || 768;
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = img.width || fallbackWidth;
      canvas.height = img.height || fallbackHeight;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => {
        if (!blob) return;
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `constellation_${this.currentSystem}.png`;
        link.click();
        URL.revokeObjectURL(link.href);
      });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      this.showToast('Export PNG échoué.', 'error');
    };
    img.src = url;
    this.addJournalEntry({ action: 'export:png' });
  }

  observeResize() {
    if (!this.viewport2d) return;
    this.resizeObserver = new ResizeObserver(() => {
      this.bus.emit('viewport:resize');
      this.reload2D();
    });
    this.resizeObserver.observe(this.viewport2d);
  }

  async enable3D() {
    if (this.overlay3d) return;
    try {
      const module = await import(THREE_OVERLAY_PATH);
      if (module?.Constellation3DOverlay) {
        this.overlay3d = new module.Constellation3DOverlay(this.viewport3d, {
          bus: this.bus,
          getNodes: () => this.currentState.nodes,
          onNodeMove: (id, position, phase) => {
            const node = this.currentState.nodes.find((item) => item.id === id);
            if (!node) return;
            node.x = position.x;
            node.y = position.y;
            if (phase === 'move') {
              this.queueRealtimeSync();
            } else if (phase === 'end') {
              this.scheduleSave('3d-drag');
              this.addJournalEntry({ action: 'drag', node: id });
            }
          },
        });
        await this.overlay3d.init();
        this.viewport3d?.setAttribute('aria-hidden', 'false');
        this.bus.emit('overlay:ready');
        this.overlay3d.setGrid(Boolean(this.currentState.styles.grid));
        this.overlay3d.updateFrom2D(this.currentState.nodes);
        this.showToast('Overlay 3D activé.', 'success');
      }
    } catch (error) {
      console.error('constellation: 3d overlay failed', error);
      this.showToast('Impossible de charger la surcouche 3D.', 'error');
      writeStorage('const:3d:on', '0');
      const toggle = this.toolbar?.querySelector('input[data-action="toggle-3d"]');
      if (toggle instanceof HTMLInputElement) {
        toggle.checked = false;
      }
    }
  }

  disable3D() {
    if (this.overlay3d) {
      this.overlay3d.destroy();
      this.overlay3d = null;
    }
    this.viewport3d?.setAttribute('aria-hidden', 'true');
    this.showToast('Overlay 3D désactivé.');
  }

  is3DEnabled() {
    return readStorage('const:3d:on') === '1';
  }

  toggleNodeSelection(id) {
    this.selectedNodeId = id;
    const node = this.currentState.nodes.find((item) => item.id === id);
    this.renderNodeForm(node || null);
  }

  destroy() {
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
    if (this.keyHandler) {
      document.removeEventListener('keydown', this.keyHandler);
    }
    if (this.toastTimeout) {
      clearTimeout(this.toastTimeout);
    }
    if (this.pendingRealtimeSync) {
      cancelAnimationFrame(this.pendingRealtimeSync);
      this.pendingRealtimeSync = null;
    }
    window.removeEventListener('constellation:select', this.handleExternalSelect);
    this.disable3D();
  }
}

function ensureStyle() {
  if (document.querySelector(`link[href="${STYLE_URL}"]`)) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLE_URL;
  document.head.appendChild(link);
}

async function loadView(target) {
  const response = await fetch(VIEW_URL);
  const html = await response.text();
  target.innerHTML = html;
}

export function init() {
  if (initialized) return;
  container = document.querySelector('section[data-tab="constellation"]');
  if (!container) return;
  ensureStyle();
  loadView(container)
    .then(() => {
      appInstance = new ConstellationApp(container.querySelector('section[data-module="constellation"]') || container);
      appInstance.init();
      destroyCallback = () => {
        appInstance.destroy();
        appInstance = null;
      };
    })
    .catch((error) => {
      console.error('constellation: view load failed', error);
    });
  initialized = true;
}

export function show() {
  if (!container) return;
  container.classList.remove('hidden');
  if (appInstance) {
    appInstance.reload2D();
  }
}

export function hide() {
  if (!container) return;
  container.classList.add('hidden');
}

export function destroy() {
  if (!initialized) return;
  destroyCallback?.();
  container = null;
  initialized = false;
}

