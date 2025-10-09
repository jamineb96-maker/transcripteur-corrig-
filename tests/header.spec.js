const assert = require('node:assert/strict');

const windowListeners = new Map();
const documentListeners = new Map();
const frameQueue = [];

function toCamelCase(segment) {
  return segment.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
}

function toDataAttr(key) {
  return key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}

function createMockElement(tagName) {
  const listeners = new Map();
  const classSet = new Set();
  const datasetStore = {};
  const attributes = {};

  const element = {
    tagName: tagName.toUpperCase(),
    parentElement: null,
    hidden: false,
    disabled: false,
    textContent: '',
    innerHTML: '',
    id: '',
    _width: 120,
    _clientWidth: 320,
    _offsetWidth: 48,
    offsetParent: {},
    dataset: new Proxy(datasetStore, {
      set(_target, key, value) {
        datasetStore[key] = String(value);
        const attrName = `data-${toDataAttr(key)}`;
        attributes[attrName] = String(value);
        return true;
      },
      get(_target, key) {
        return datasetStore[key];
      },
      deleteProperty(_target, key) {
        delete datasetStore[key];
        const attrName = `data-${toDataAttr(key)}`;
        delete attributes[attrName];
        return true;
      },
    }),
    attributes,
    _children: [],
    classList: {
      add(cls) {
        classSet.add(cls);
      },
      remove(cls) {
        classSet.delete(cls);
      },
      toggle(cls, force) {
        if (force === true) {
          classSet.add(cls);
          return true;
        }
        if (force === false) {
          classSet.delete(cls);
          return false;
        }
        if (classSet.has(cls)) {
          classSet.delete(cls);
          return false;
        }
        classSet.add(cls);
        return true;
      },
      contains(cls) {
        return classSet.has(cls);
      },
    },
    addEventListener(type, handler) {
      const entries = listeners.get(type) || [];
      entries.push(handler);
      listeners.set(type, entries);
    },
    removeEventListener(type, handler) {
      const entries = listeners.get(type) || [];
      listeners.set(
        type,
        entries.filter((fn) => fn !== handler),
      );
    },
    dispatchEvent(type, event = {}) {
      const enriched = {
        preventDefault() {},
        stopPropagation() {},
        ...event,
        target: event.target || element,
        currentTarget: element,
      };
      const entries = listeners.get(type) || [];
      entries.forEach((fn) => fn(enriched));
    },
    appendChild(child) {
      if (child.parentElement) {
        child.parentElement.removeChild(child);
      }
      child.parentElement = element;
      element._children.push(child);
      return child;
    },
    removeChild(child) {
      const index = element._children.indexOf(child);
      if (index !== -1) {
        element._children.splice(index, 1);
        child.parentElement = null;
      }
      return child;
    },
    replaceChildren(...nodes) {
      element._children.slice().forEach((child) => {
        element.removeChild(child);
      });
      nodes.forEach((node) => {
        if (node) {
          element.appendChild(node);
        }
      });
    },
    remove() {
      if (element.parentElement) {
        element.parentElement.removeChild(element);
      }
    },
    contains(target) {
      if (target === element) {
        return true;
      }
      return element._children.some((child) => child === target || child.contains(target));
    },
    focus() {
      document.activeElement = element;
    },
    blur() {
      if (document.activeElement === element) {
        document.activeElement = null;
      }
    },
    setAttribute(name, value) {
      attributes[name] = String(value);
      if (name === 'class') {
        classSet.clear();
        String(value)
          .split(/\s+/)
          .filter(Boolean)
          .forEach((cls) => classSet.add(cls));
      } else if (name === 'id') {
        element.id = String(value);
      } else if (name === 'hidden') {
        element.hidden = value === '' || value === 'true' || value === true;
      } else if (name.startsWith('data-')) {
        const dataKey = toCamelCase(name.slice(5));
        datasetStore[dataKey] = String(value);
      }
    },
    getAttribute(name) {
      if (name === 'class') {
        return Array.from(classSet).join(' ');
      }
      if (name === 'id') {
        return element.id || null;
      }
      if (name === 'hidden') {
        return element.hidden ? '' : null;
      }
      if (name.startsWith('data-')) {
        const dataKey = toCamelCase(name.slice(5));
        return datasetStore[dataKey] ?? null;
      }
      return Object.prototype.hasOwnProperty.call(attributes, name) ? attributes[name] : null;
    },
    hasAttribute(name) {
      return element.getAttribute(name) !== null;
    },
    removeAttribute(name) {
      delete attributes[name];
      if (name === 'class') {
        classSet.clear();
      } else if (name === 'id') {
        element.id = '';
      } else if (name === 'hidden') {
        element.hidden = false;
      } else if (name.startsWith('data-')) {
        const dataKey = toCamelCase(name.slice(5));
        delete datasetStore[dataKey];
      }
    },
    querySelector(selector) {
      const results = element.querySelectorAll(selector);
      return results.length > 0 ? results[0] : null;
    },
    querySelectorAll(selector) {
      const results = [];
      element._children.forEach((child) => {
        if (matchesSelector(child, selector)) {
          results.push(child);
        }
        child.querySelectorAll(selector).forEach((grandChild) => results.push(grandChild));
      });
      return results;
    },
    getBoundingClientRect() {
      return { width: element._width };
    },
  };

  Object.defineProperty(element, 'children', {
    get() {
      return element._children;
    },
  });

  Object.defineProperty(element, 'className', {
    get() {
      return Array.from(classSet).join(' ');
    },
    set(value) {
      classSet.clear();
      String(value)
        .split(/\s+/)
        .filter(Boolean)
        .forEach((cls) => classSet.add(cls));
    },
  });

  Object.defineProperty(element, 'clientWidth', {
    get() {
      return element._clientWidth;
    },
    set(value) {
      element._clientWidth = Number(value);
    },
  });

  Object.defineProperty(element, 'offsetWidth', {
    get() {
      return element._offsetWidth;
    },
    set(value) {
      element._offsetWidth = Number(value);
    },
  });

  return element;
}

function matchesSelector(element, selector) {
  if (!selector) {
    return false;
  }
  const trimmed = selector.trim();
  if (trimmed.includes(',')) {
    return trimmed
      .split(',')
      .some((part) => matchesSelector(element, part));
  }
  const notMatch = trimmed.match(/^(.*):not\((.*)\)$/);
  if (notMatch) {
    const [, base, negated] = notMatch;
    return matchesSelector(element, base) && !matchesSelector(element, negated);
  }
  if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
    const content = trimmed.slice(1, -1);
    const [attr, rawValue] = content.split('=');
    if (rawValue) {
      const expected = rawValue.replace(/^"|"$/g, '').replace(/^'|'$/g, '');
      const actual = element.getAttribute(attr);
      return actual === expected;
    }
    return element.getAttribute(content) !== null;
  }
  if (trimmed.startsWith('.')) {
    return element.classList.contains(trimmed.slice(1));
  }
  if (trimmed.startsWith('#')) {
    return element.id === trimmed.slice(1);
  }
  if (trimmed.includes('.')) {
    const [tag, cls] = trimmed.split('.');
    if (tag && tag.length > 0 && element.tagName.toLowerCase() !== tag.toLowerCase()) {
      return false;
    }
    return element.classList.contains(cls);
  }
  if (trimmed.includes('#')) {
    const [tag, id] = trimmed.split('#');
    if (tag && tag.length > 0 && element.tagName.toLowerCase() !== tag.toLowerCase()) {
      return false;
    }
    return element.id === id;
  }
  if (trimmed === '*') {
    return true;
  }
  return element.tagName.toLowerCase() === trimmed.toLowerCase();
}

function emitWindow(type, event = {}) {
  const listeners = windowListeners.get(type) || [];
  listeners.slice().forEach((fn) => fn(event));
}

const document = {
  body: createMockElement('body'),
  activeElement: null,
  createElement(tagName) {
    return createMockElement(tagName);
  },
  querySelector(selector) {
    const results = this.querySelectorAll(selector);
    return results.length > 0 ? results[0] : null;
  },
  querySelectorAll(selector) {
    const results = [];
    if (!this.body) {
      return results;
    }
    if (matchesSelector(this.body, selector)) {
      results.push(this.body);
    }
    this.body.querySelectorAll(selector).forEach((node) => results.push(node));
    return results;
  },
  addEventListener(type, handler, options) {
    const entries = documentListeners.get(type) || [];
    entries.push(handler);
    documentListeners.set(type, entries);
    return options;
  },
  removeEventListener(type, handler) {
    const entries = documentListeners.get(type) || [];
    documentListeners.set(
      type,
      entries.filter((fn) => fn !== handler),
    );
  },
};

global.document = document;

global.window = {
  addEventListener(type, handler) {
    const entries = windowListeners.get(type) || [];
    entries.push(handler);
    windowListeners.set(type, entries);
  },
  removeEventListener(type, handler) {
    const entries = windowListeners.get(type) || [];
    windowListeners.set(
      type,
      entries.filter((fn) => fn !== handler),
    );
  },
  requestAnimationFrame(callback) {
    frameQueue.push(callback);
    return frameQueue.length;
  },
  cancelAnimationFrame(id) {
    if (!Number.isFinite(id)) {
      return;
    }
    const index = id - 1;
    if (index >= 0 && index < frameQueue.length) {
      frameQueue.splice(index, 1);
    }
  },
};

global.requestAnimationFrame = global.window.requestAnimationFrame.bind(global.window);
global.cancelAnimationFrame = global.window.cancelAnimationFrame.bind(global.window);

global.setTimeout = setTimeout;
global.clearTimeout = clearTimeout;

globalThis.navigator = { userAgent: 'node-test' };

globalThis.console = console;

document.body.appendChild = function appendChild(child) {
  if (child.parentElement) {
    child.parentElement.removeChild(child);
  }
  child.parentElement = document.body;
  document.body._children.push(child);
  return child;
};

document.body._children = [];

document.body.querySelectorAll = function querySelectorAll(selector) {
  const results = [];
  document.body._children.forEach((child) => {
    if (matchesSelector(child, selector)) {
      results.push(child);
    }
    child.querySelectorAll(selector).forEach((node) => results.push(node));
  });
  return results;
};

document.body.removeChild = function removeChild(child) {
  const index = document.body._children.indexOf(child);
  if (index !== -1) {
    document.body._children.splice(index, 1);
    child.parentElement = null;
  }
  return child;
};

document.body.contains = function contains(target) {
  if (target === document.body) {
    return true;
  }
  return document.body._children.some((child) => child === target || child.contains(target));
};

(async () => {
  const { initHeader } = await import('../client/components/header.js');

  const headerPrimary = createMockElement('header');
  headerPrimary.classList.add('app-header');
  const brand = createMockElement('a');
  brand.classList.add('brand');
  const navHost = createMockElement('nav');
  navHost.classList.add('primary-nav');
  navHost._clientWidth = 180;
  headerPrimary.appendChild(brand);
  headerPrimary.appendChild(navHost);

  const headerDuplicate = createMockElement('header');
  headerDuplicate.classList.add('app-header');
  document.body.appendChild(headerPrimary);
  document.body.appendChild(headerDuplicate);

  const navigations = [];
  const controller = initHeader({
    tabs: ['pre_session', 'post_session', 'library', 'anatomie3d'],
    onNavigate: (tabId) => navigations.push(tabId),
  });

  assert.equal(
    document.querySelectorAll('header.app-header').length,
    1,
    'Only one header should remain in the document',
  );
  assert.equal(headerDuplicate.parentElement, null, 'Duplicate headers should be removed from the DOM');

  const wrapper = navHost.querySelector('.tabs__wrapper');
  const primaryNav = wrapper.querySelector('.tabs__primary');
  const overflowToggle = wrapper.querySelector('#menu-more-trigger');
  const overflowMenu = wrapper.querySelector('#menu-more');

  primaryNav._clientWidth = 180;
  overflowToggle._offsetWidth = 36;

  const anchors = primaryNav.querySelectorAll('a');
  anchors.forEach((anchor) => {
    anchor._width = 110;
  });

  while (frameQueue.length > 0) {
    const next = frameQueue.shift();
    next();
  }

  assert.equal(anchors.length, 4, 'All tab anchors should be created');

  overflowToggle.dispatchEvent('click', { preventDefault() {} });
  assert.equal(overflowMenu.dataset.open, 'true', 'Overflow menu should open on toggle click');

  emitWindow('resize');
  assert.equal(overflowMenu.dataset.open, 'false', 'Overflow menu should close on window resize');

  overflowToggle.dispatchEvent('click', { preventDefault() {} });
  assert.equal(overflowMenu.dataset.open, 'true', 'Overflow menu should reopen on toggle click');
  controller.closeOverflowMenu();
  assert.equal(overflowMenu.dataset.open, 'false', 'closeOverflowMenu should hide the overflow menu');

  brand.dispatchEvent('click', { preventDefault() {} });
  assert.deepEqual(navigations, ['home'], 'Brand click should emit a navigation event to home');

  const initialResizeCount = (windowListeners.get('resize') || []).length;
  assert.ok(initialResizeCount >= 1, 'Header should register resize listeners');

  const controllerSecond = initHeader({ tabs: ['pre_session'] });
  const resizeListenersAfter = windowListeners.get('resize') || [];
  assert.equal(
    resizeListenersAfter.length,
    initialResizeCount,
    'Reinitialising the header should not accumulate resize listeners',
  );

  controllerSecond.destroy();
  controller.destroy();

  console.log('header.spec.js passed');
})().catch((error) => {
  console.error('header.spec.js failed');
  console.error(error);
  process.exit(1);
});
