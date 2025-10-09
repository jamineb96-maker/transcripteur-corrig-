import assert from 'node:assert/strict';

import { attachDropdown } from '../../client/components/dropdown.js';

function createListenersRegistry() {
  const registry = new Map();
  return {
    add(type, handler) {
      const entries = registry.get(type) || [];
      entries.push(handler);
      registry.set(type, entries);
    },
    remove(type, handler) {
      const entries = registry.get(type) || [];
      registry.set(
        type,
        entries.filter((fn) => fn !== handler),
      );
    },
    emit(type, event = {}) {
      const entries = registry.get(type) || [];
      entries.forEach((fn) => fn(event));
    },
    count(type) {
      const entries = registry.get(type) || [];
      return entries.length;
    },
  };
}

const documentListeners = createListenersRegistry();
const windowListeners = createListenersRegistry();

function createMockElement(name) {
  const listeners = new Map();
  const children = [];
  const classValues = new Set();
  const element = {
    name,
    attributes: {},
    dataset: {},
    hidden: false,
    disabled: false,
    focused: false,
    offsetParent: {},
    parentElement: null,
    classList: {
      add(cls) {
        classValues.add(cls);
      },
      remove(cls) {
        classValues.delete(cls);
      },
      toggle(cls, force) {
        if (force === true) {
          classValues.add(cls);
          return true;
        }
        if (force === false) {
          classValues.delete(cls);
          return false;
        }
        if (classValues.has(cls)) {
          classValues.delete(cls);
          return false;
        }
        classValues.add(cls);
        return true;
      },
      contains(cls) {
        return classValues.has(cls);
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
      children.push(child);
      child.parentElement = element;
      return child;
    },
    querySelectorAll() {
      return children;
    },
    contains(target) {
      if (target === element) {
        return true;
      }
      return children.includes(target);
    },
    setAttribute(attr, value) {
      this.attributes[attr] = String(value);
      if (attr === 'hidden') {
        this.hidden = value === '' || value === 'true' || value === true;
      }
    },
    getAttribute(attr) {
      return Object.prototype.hasOwnProperty.call(this.attributes, attr)
        ? this.attributes[attr]
        : null;
    },
    removeAttribute(attr) {
      delete this.attributes[attr];
      if (attr === 'hidden') {
        this.hidden = false;
      }
    },
    hasAttribute(attr) {
      return Object.prototype.hasOwnProperty.call(this.attributes, attr);
    },
    focus() {
      document.activeElement = element;
      element.focused = true;
    },
  };
  return element;
}

function dispatchDocumentEvent(type, event = {}) {
  const enriched = {
    preventDefault() {},
    ...event,
  };
  if (typeof enriched.composedPath !== 'function') {
    enriched.composedPath = () => {
      const target = enriched.target || null;
      return target ? [target] : [];
    };
  }
  documentListeners.emit(type, enriched);
}

function dispatchWindowEvent(type, event = {}) {
  windowListeners.emit(type, event);
}

Object.defineProperty(globalThis, 'document', {
  value: {
    activeElement: null,
    addEventListener(type, handler) {
      documentListeners.add(type, handler);
    },
    removeEventListener(type, handler) {
      documentListeners.remove(type, handler);
    },
  },
  configurable: true,
});

Object.defineProperty(globalThis, 'window', {
  value: {
    requestAnimationFrame(callback) {
      callback();
      return 1;
    },
    cancelAnimationFrame() {},
    addEventListener(type, handler) {
      windowListeners.add(type, handler);
    },
    removeEventListener(type, handler) {
      windowListeners.remove(type, handler);
    },
  },
  configurable: true,
});

globalThis.cancelAnimationFrame = () => {};

const trigger = createMockElement('trigger');
const menu = createMockElement('menu');

const dropdown = attachDropdown({ trigger, menu });

assert.equal(trigger.getAttribute('aria-expanded'), 'false', 'Dropdown should be closed by default');
assert.equal(menu.hidden, true, 'Menu element should be hidden initially');
assert.equal(menu.dataset.open, 'false', 'Menu dataset should reflect closed state');

trigger.dispatchEvent('click');

assert.equal(trigger.getAttribute('aria-expanded'), 'true', 'Click should open the dropdown');
assert.equal(menu.hidden, false, 'Menu should be visible after opening');
assert.equal(menu.dataset.open, 'true', 'Menu dataset should reflect open state');

const outside = createMockElement('outside');
dispatchDocumentEvent('pointerdown', { target: outside });

assert.equal(trigger.getAttribute('aria-expanded'), 'false', 'Outside click should close the dropdown');
assert.equal(menu.hidden, true, 'Menu should be hidden after outside click');

trigger.dispatchEvent('click');

dispatchDocumentEvent('keydown', { key: 'Escape', preventDefault() {} });

assert.equal(trigger.focused, true, 'Escape should refocus the trigger button');
assert.equal(trigger.getAttribute('aria-expanded'), 'false', 'Escape should close the dropdown');

trigger.dispatchEvent('click');
document.activeElement = null;
trigger.dispatchEvent('blur');

dispatchWindowEvent('scroll');

assert.equal(menu.hidden, true, 'Window events should close the dropdown when open');

const pointerListenersBefore = documentListeners.count('pointerdown');
const dropdownAgain = attachDropdown({ trigger, menu });
const pointerListenersAfter = documentListeners.count('pointerdown');

assert.strictEqual(dropdownAgain, dropdown, 'Second attach should return the same dropdown instance');
assert.equal(pointerListenersAfter, pointerListenersBefore, 'Second attach should not register new document listeners');

dropdown.destroy();

console.log('dropdown component tests passed');
