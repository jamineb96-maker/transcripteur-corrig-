const dropdownRegistry = new WeakMap();
const dropdownInstances = new Set();

const NOOP = Object.freeze({
  open() {},
  close() {},
  toggle() {},
  destroy() {},
  isOpen: () => false,
});

const FOCUSABLE_SELECTOR = [
  '[role="menuitem"]',
  'button:not([disabled])',
  '[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([-1])',
]
  .map((selector) => `${selector}:not([aria-disabled="true"])`)
  .join(',');

function resolveElement(target) {
  if (!target) {
    return null;
  }
  if (typeof target === 'string') {
    try {
      return document.querySelector(target);
    } catch (error) {
      console.debug('[dropdown] selector resolution failed', error);
      return null;
    }
  }
  return target;
}

function wrap(label, handler) {
  return function wrappedHandler(...args) {
    try {
      return handler(...args);
    } catch (error) {
      console.debug('[dropdown]', label, error);
      return undefined;
    }
  };
}

function isEventWithin(event, elements) {
  if (!event) {
    return false;
  }
  const { target } = event;
  if (typeof event.composedPath === 'function') {
    const path = event.composedPath();
    return path.some((node) => elements.some((element) => element && element === node));
  }
  return elements.some((element) => element && (element === target || element.contains(target)));
}

function createFocusableList(menuEl) {
  return Array.from(menuEl.querySelectorAll(FOCUSABLE_SELECTOR)).filter((element) => {
    if (!element || typeof element.focus !== 'function') {
      return false;
    }
    if (element.hasAttribute('hidden') || element.getAttribute('aria-hidden') === 'true') {
      return false;
    }
    if (element.disabled) {
      return false;
    }
    return element.offsetParent !== null || element === document.activeElement;
  });
}

function focusElement(element) {
  if (!element || typeof element.focus !== 'function') {
    return;
  }
  try {
    element.focus({ preventScroll: true });
  } catch (error) {
    console.debug('[dropdown] focus error', error);
    element.focus();
  }
}

export function attachDropdown(options = {}) {
  try {
    const triggerEl = resolveElement(options.trigger);
    const menuEl = resolveElement(options.menu);

    if (!triggerEl || !menuEl) {
      return NOOP;
    }

    const registered = dropdownRegistry.get(menuEl);
    if (registered && registered.api) {
      return registered.api;
    }

    let isOpen = false;
    let rafId = null;

    const api = {
      open: () => {},
      close: () => {},
      toggle: () => {},
      destroy: () => {},
      isOpen: () => isOpen,
    };

    dropdownRegistry.set(menuEl, { api });
    dropdownInstances.add(api);

    if (!triggerEl.getAttribute('aria-haspopup')) {
      triggerEl.setAttribute('aria-haspopup', 'true');
    }
    triggerEl.setAttribute('aria-expanded', 'false');
    if (menuEl.id && !triggerEl.getAttribute('aria-controls')) {
      triggerEl.setAttribute('aria-controls', menuEl.id);
    }
    if (!menuEl.getAttribute('role')) {
      menuEl.setAttribute('role', 'menu');
    }
    menuEl.dataset.open = 'false';
    menuEl.setAttribute('hidden', '');
    menuEl.dataset.dropdownBound = '1';

    const closeOthers = wrap('close others', () => {
      dropdownInstances.forEach((instance) => {
        if (instance !== api && typeof instance.close === 'function') {
          instance.close();
        }
      });
    });

    const setState = wrap('set state', (nextOpen) => {
      if (isOpen === nextOpen) {
        return;
      }
      isOpen = nextOpen;
      triggerEl.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
      menuEl.dataset.open = nextOpen ? 'true' : 'false';
      if (nextOpen) {
        menuEl.removeAttribute('hidden');
      } else {
        menuEl.setAttribute('hidden', '');
      }
    });

    const ensureFocusWithin = () => {
      if (document.activeElement === triggerEl) {
        return true;
      }
      return menuEl.contains(document.activeElement);
    };

    const scheduleCloseIfFocusMoves = wrap('schedule blur close', () => {
      if (rafId) {
        cancelAnimationFrame(rafId);
      }
      rafId = window.requestAnimationFrame(() => {
        rafId = null;
        if (!ensureFocusWithin()) {
          api.close();
        }
      });
    });

    const focusFirstItem = wrap('focus first', () => {
      const items = createFocusableList(menuEl);
      if (items.length > 0) {
        focusElement(items[0]);
      }
    });

    const focusLastItem = wrap('focus last', () => {
      const items = createFocusableList(menuEl);
      if (items.length > 0) {
        focusElement(items[items.length - 1]);
      }
    });

    const handleMenuKeyDown = wrap('menu keydown', (event) => {
      if (!isOpen) {
        return;
      }
      const items = createFocusableList(menuEl);
      if (items.length === 0) {
        return;
      }
      const currentIndex = items.indexOf(document.activeElement);
      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault();
          if (currentIndex === -1 || currentIndex === items.length - 1) {
            focusElement(items[0]);
          } else {
            focusElement(items[currentIndex + 1]);
          }
          break;
        case 'ArrowUp':
          event.preventDefault();
          if (currentIndex <= 0) {
            focusElement(items[items.length - 1]);
          } else {
            focusElement(items[currentIndex - 1]);
          }
          break;
        case 'Home':
          event.preventDefault();
          focusElement(items[0]);
          break;
        case 'End':
          event.preventDefault();
          focusElement(items[items.length - 1]);
          break;
        case 'Escape':
        case 'Esc':
          event.preventDefault();
          api.close({ focusTrigger: true });
          break;
        default:
          break;
      }
    });

    const handleDocumentPointer = wrap('document pointerdown', (event) => {
      if (!isOpen) {
        return;
      }
      if (isEventWithin(event, [triggerEl, menuEl])) {
        return;
      }
      api.close();
    });

    const handleDocumentKey = wrap('document keydown', (event) => {
      if (!isOpen) {
        return;
      }
      if (event.key === 'Escape' || event.key === 'Esc') {
        event.preventDefault();
        api.close({ focusTrigger: true });
      }
    });

    const handleWindowChange = wrap('window change', () => {
      if (!isOpen) {
        return;
      }
      api.close();
    });

    const handleTriggerClick = wrap('trigger click', (event) => {
      event.preventDefault();
      api.toggle();
    });

    const handleTriggerKeyDown = wrap('trigger keydown', (event) => {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        if (!isOpen) {
          api.open();
        }
        focusFirstItem();
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (!isOpen) {
          api.open();
        }
        focusLastItem();
      } else if (event.key === 'Escape' || event.key === 'Esc') {
        event.preventDefault();
        api.close({ focusTrigger: true });
      }
    });

    const openImpl = wrap('open', () => {
      if (isOpen) {
        return;
      }
      closeOthers();
      setState(true);
      focusFirstItem();
    });

    const closeImpl = wrap('close', (options = {}) => {
      if (!isOpen) {
        return;
      }
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      setState(false);
      if (options.focusTrigger) {
        focusElement(triggerEl);
      }
    });

    const toggleImpl = wrap('toggle', () => {
      if (isOpen) {
        api.close();
      } else {
        api.open();
      }
    });

    const destroyImpl = wrap('destroy', () => {
      api.close();
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      triggerEl.removeEventListener('click', handleTriggerClick);
      triggerEl.removeEventListener('keydown', handleTriggerKeyDown);
      triggerEl.removeEventListener('blur', scheduleCloseIfFocusMoves);
      menuEl.removeEventListener('keydown', handleMenuKeyDown);
      menuEl.removeEventListener('focusout', scheduleCloseIfFocusMoves);
      document.removeEventListener('pointerdown', handleDocumentPointer, true);
      document.removeEventListener('keydown', handleDocumentKey, true);
      window.removeEventListener('scroll', handleWindowChange, true);
      window.removeEventListener('resize', handleWindowChange);
      window.removeEventListener('orientationchange', handleWindowChange);
      window.removeEventListener('hashchange', handleWindowChange);
      window.removeEventListener('popstate', handleWindowChange);
      dropdownInstances.delete(api);
      dropdownRegistry.delete(menuEl);
      delete menuEl.dataset.dropdownBound;
    });

    api.open = openImpl;
    api.close = closeImpl;
    api.toggle = toggleImpl;
    api.destroy = destroyImpl;

    triggerEl.addEventListener('click', handleTriggerClick);
    triggerEl.addEventListener('keydown', handleTriggerKeyDown);
    triggerEl.addEventListener('blur', scheduleCloseIfFocusMoves);
    menuEl.addEventListener('keydown', handleMenuKeyDown);
    menuEl.addEventListener('focusout', scheduleCloseIfFocusMoves);
    document.addEventListener('pointerdown', handleDocumentPointer, true);
    document.addEventListener('keydown', handleDocumentKey, true);
    window.addEventListener('scroll', handleWindowChange, true);
    window.addEventListener('resize', handleWindowChange);
    window.addEventListener('orientationchange', handleWindowChange);
    window.addEventListener('hashchange', handleWindowChange);
    window.addEventListener('popstate', handleWindowChange);

    return api;
  } catch (error) {
    console.debug('[dropdown] attach failed', error);
    return NOOP;
  }
}

export default {
  attachDropdown,
};
