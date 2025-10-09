import assert from 'node:assert/strict';

const retryCalls = [];
const originalConsoleError = console.error;
console.error = () => {};

function createRetryButton() {
  let handler = null;
  let once = false;
  return {
    disabled: false,
    textContent: 'Réessayer',
    addEventListener(type, fn, options) {
      if (type === 'click') {
        handler = fn;
        once = Boolean(options && options.once);
      }
    },
    trigger() {
      if (!handler) {
        return;
      }
      handler({ preventDefault() {}, target: this });
      if (once) {
        handler = null;
      }
    },
  };
}

function createElement(tagName) {
  const classValues = new Set();
  const element = {
    tagName,
    dataset: {},
    className: '',
    hidden: false,
    children: [],
    parentElement: null,
    _html: '',
    _retryButton: null,
    _statusElement: null,
    classList: {
      add(cls) {
        classValues.add(cls);
        element.className = Array.from(classValues).join(' ');
      },
      remove(cls) {
        classValues.delete(cls);
        element.className = Array.from(classValues).join(' ');
      },
      contains(cls) {
        return classValues.has(cls);
      },
    },
    appendChild(child) {
      child.parentElement = element;
      element.children.push(child);
      return child;
    },
    querySelector(selector) {
      if (selector === '[data-tab-status]') {
        return element._statusElement;
      }
      if (selector === '[data-action="retry-tab"]') {
        return element._retryButton;
      }
      return null;
    },
    set innerHTML(value) {
      element._html = value;
      if (!value) {
        element._statusElement = null;
        element._retryButton = null;
        return;
      }
      if (value && value.includes('data-tab-status')) {
        element._statusElement = {
          removed: false,
          remove() {
            this.removed = true;
          },
        };
      }
      if (value && value.includes('data-action="retry-tab"')) {
        element._retryButton = createRetryButton();
      }
    },
    get innerHTML() {
      return element._html;
    },
  };
  return element;
}

const tabRoot = createElement('div');

tabRoot.querySelector = (selector) => {
  if (selector === 'section[data-tab="library"]') {
    return tabRoot.children.find((child) => child.dataset.tab === 'library') || null;
  }
  return null;
};

globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail || null;
  }
};

globalThis.window = {
  ASSET_VERSION: '',
  requestTabReload: (tabId) => retryCalls.push(tabId),
  retryTab: null,
  dispatchEvent() {},
  addEventListener() {},
  removeEventListener() {},
};

globalThis.document = {
  querySelector(selector) {
    if (selector === '[data-tab-root]') {
      return tabRoot;
    }
    return null;
  },
  createElement: (tagName) => createElement(tagName),
};

globalThis.fetch = async (url) => {
  if (url.includes('/static/tabs/library/index.html')) {
    return {
      ok: false,
      status: 404,
      statusText: 'Not Found',
    };
  }
  return {
    ok: true,
    json: async () => ({}),
    text: async () => '',
  };
};

const library = await import('../../client/tabs/library/index.js');

library.init();

const container = tabRoot.querySelector('section[data-tab="library"]');
assert.ok(container, 'Init should create a container for the library tab');
assert.equal(container.dataset.tab, 'library', 'Container should be tagged with the library tab id');

let caughtError = null;
try {
  await library.show();
} catch (error) {
  caughtError = error;
}

assert.ok(caughtError, 'show() should reject when the view fails to load');
assert.equal(caughtError?.handled, true, 'Error should be marked as handled');
assert.equal(container.dataset.loaded, 'false', 'Container should remain flagged as not loaded');
assert.ok(
  container.innerHTML.includes('Module bibliothèque indisponible'),
  'A local error message should be rendered inside the tab container',
);

const retryButton = container._retryButton;
assert.ok(retryButton, 'A retry button should be rendered inside the tab');
assert.equal(retryCalls.length, 0, 'Retry should not trigger automatically');

retryButton.trigger();

assert.equal(retryCalls.length, 1, 'Retry button should dispatch a reload request');
assert.equal(retryCalls[0], 'library', 'Retry request should target the library tab');
assert.equal(retryButton.disabled, true, 'Retry button should be disabled after activation');
assert.equal(retryButton.textContent, 'Nouvelle tentative…', 'Retry button label should update after activation');

library.destroy();

console.error = originalConsoleError;

console.log('library error handling tests passed');
