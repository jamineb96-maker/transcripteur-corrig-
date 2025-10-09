import { attachDropdown } from './dropdown.js';

const DROPDOWN_API_KEY = Symbol('dropdownApi');
const ACTIVE_HEADER_KEY = Symbol('activeHeaderController');

const TAB_METADATA = {
  pre_session: {
    label: 'Pré‑séance',
    shortLabel: 'Pré‑séance',
  },
  post_session: {
    label: 'Post‑séance',
    shortLabel: 'Post‑séance',
  },
  journal_critique: {
    label: 'Journal critique',
    shortLabel: 'Journal critique',
  },
  documents_aide: {
    label: 'Documents d’aide',
    shortLabel: 'Documents d’aide',
  },
  library: {
    label: 'Bibliothèque',
    shortLabel: 'Bibliothèque',
  },
  constellation: {
    label: 'Constellation',
    shortLabel: 'Constellation',
  },
  anatomie3d: {
    label: 'Anatomie 3D',
    shortLabel: 'Anatomie 3D',
  },
  facturation: {
    label: 'Facturation',
    shortLabel: 'Facturation',
  },
  agenda: {
    label: 'Agenda',
    shortLabel: 'Agenda',
  },
  budget: {
    label: 'Budget cognitif',
    shortLabel: 'Budget cognitif',
  },
};

function getTabMetadata(tabId) {
  return TAB_METADATA[tabId] || {
    label: tabId,
    shortLabel: tabId,
  };
}

function debounce(fn, delay = 150) {
  let timer = null;
  return (...args) => {
    if (timer) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, delay);
  };
}

function ensureSingleHeader() {
  const headers = Array.from(document.querySelectorAll('header.app-header'));
  if (headers.length === 0) {
    return null;
  }
  const [primary, ...duplicates] = headers;
  duplicates.forEach((node) => {
    if (node && node.parentElement) {
      node.parentElement.removeChild(node);
    }
  });
  return primary;
}

function cleanupController(controller) {
  if (!controller || typeof controller.destroy !== 'function') {
    return;
  }
  try {
    controller.destroy();
  } catch (error) {
    console.debug('[header] cleanup failed', error);
  }
}

export function initHeader(options = {}) {
  const { tabs = [], onNavigate } = options;

  const fallback = {
    setActiveTab() {},
    refreshLayout() {},
    elements: {},
    closeOverflowMenu() {},
    destroy() {},
  };

  const existing = document[ACTIVE_HEADER_KEY];
  if (existing) {
    cleanupController(existing);
    document[ACTIVE_HEADER_KEY] = null;
  }

  const header = ensureSingleHeader();
  if (!header) {
    return fallback;
  }

  const navHost = header.querySelector('nav.primary-nav') || header.querySelector('nav.tabs');
  if (!navHost) {
    return fallback;
  }

  while (navHost.firstChild) {
    navHost.removeChild(navHost.firstChild);
  }

  const cleanupFns = [];
  const registerCleanup = (fn) => {
    if (typeof fn === 'function') {
      cleanupFns.push(fn);
    }
  };

  const navWrapper = document.createElement('div');
  navWrapper.className = 'tabs__wrapper';

  const primaryNav = document.createElement('div');
  primaryNav.className = 'tabs__primary';
  primaryNav.id = 'primaryNav';

  const overflowContainer = document.createElement('div');
  overflowContainer.className = 'tabs__overflow';

  const overflowToggle = document.createElement('button');
  overflowToggle.type = 'button';
  overflowToggle.className = 'tabs__more';
  overflowToggle.id = 'menu-more-trigger';
  overflowToggle.setAttribute('aria-haspopup', 'true');
  overflowToggle.setAttribute('aria-expanded', 'false');
  overflowToggle.setAttribute('aria-controls', 'menu-more');
  overflowToggle.setAttribute('aria-label', 'Afficher plus d’onglets');
  overflowToggle.innerHTML = 'Plus ▾';

  const overflowMenu = document.createElement('div');
  overflowMenu.id = 'menu-more';
  overflowMenu.className = 'tabs__menu';
  overflowMenu.setAttribute('role', 'menu');
  overflowMenu.setAttribute('aria-labelledby', 'menu-more-trigger');
  overflowMenu.hidden = true;
  overflowMenu.dataset.open = 'false';

  const overflowList = document.createElement('div');
  overflowList.className = 'tabs__menu-items';
  overflowMenu.appendChild(overflowList);

  overflowContainer.appendChild(overflowToggle);
  overflowContainer.appendChild(overflowMenu);

  navWrapper.appendChild(primaryNav);
  navWrapper.appendChild(overflowContainer);
  navHost.appendChild(navWrapper);

  const noopDropdown = {
    open() {},
    close() {},
    toggle() {},
    destroy() {},
  };

  let dropdown = noopDropdown;
  if (overflowMenu.dataset.bound === '1' && overflowMenu[DROPDOWN_API_KEY]) {
    dropdown = overflowMenu[DROPDOWN_API_KEY];
  } else {
    try {
      dropdown = attachDropdown({ trigger: overflowToggle, menu: overflowMenu });
      if (dropdown && typeof dropdown.close === 'function') {
        overflowMenu.dataset.bound = '1';
        overflowMenu[DROPDOWN_API_KEY] = dropdown;
      }
    } catch (error) {
      console.debug('[dropdown] header attach failed', error);
    }
  }
  registerCleanup(() => {
    if (dropdown && typeof dropdown.destroy === 'function') {
      dropdown.destroy();
    } else if (dropdown && typeof dropdown.close === 'function') {
      dropdown.close();
    }
  });

  const closeOverflowMenu = () => {
    if (dropdown && typeof dropdown.close === 'function') {
      dropdown.close();
    }
  };

  const brandLink = header.querySelector('.brand');
  if (brandLink) {
    const handleBrandClick = (event) => {
      event.preventDefault();
      closeOverflowMenu();
      if (typeof onNavigate === 'function') {
        onNavigate('home');
      }
    };
    brandLink.addEventListener('click', handleBrandClick);
    registerCleanup(() => {
      brandLink.removeEventListener('click', handleBrandClick);
    });
  }

  const items = tabs.map((tabId) => {
    const meta = getTabMetadata(tabId);
    const anchor = document.createElement('a');
    anchor.href = `#${tabId}`;
    anchor.dataset.tabLink = tabId;
    anchor.className = 'tabs__item nav-link';
    anchor.textContent = meta.label;
    anchor.setAttribute('data-tab-target', tabId);
    anchor.addEventListener('click', (event) => {
      event.preventDefault();
      closeOverflowMenu();
      if (typeof onNavigate === 'function') {
        onNavigate(tabId);
      }
    });
    primaryNav.appendChild(anchor);

    const overflowBtn = document.createElement('button');
    overflowBtn.type = 'button';
    overflowBtn.className = 'tabs__menu-item';
    overflowBtn.dataset.tabTarget = tabId;
    overflowBtn.dataset.tabLink = tabId;
    overflowBtn.setAttribute('role', 'menuitem');
    overflowBtn.textContent = meta.shortLabel;
    overflowBtn.hidden = true;
    overflowBtn.addEventListener('click', (event) => {
      event.preventDefault();
      closeOverflowMenu();
      if (typeof onNavigate === 'function') {
        onNavigate(tabId);
      }
    });
    overflowList.appendChild(overflowBtn);

    return {
      id: tabId,
      anchor,
      overflowBtn,
      measuredWidth: 0,
    };
  });

  function measureItems() {
    items.forEach((item) => {
      item.anchor.hidden = false;
    });
    // Force layout measurement
    items.forEach((item) => {
      item.measuredWidth = item.anchor.getBoundingClientRect().width;
    });
  }

  function applyPriorityLayout() {
    measureItems();

    const toggleWasHidden = overflowToggle.hidden;
    if (toggleWasHidden) {
      overflowToggle.hidden = false;
    }

    const containerWidth = primaryNav.clientWidth;
    const moreButtonWidth = overflowToggle.offsetWidth || 0;
    let used = 0;
    let overflowIndex = items.length;

    for (let index = 0; index < items.length; index += 1) {
      const width = items[index].measuredWidth;
      if (used + width > containerWidth) {
        overflowIndex = index;
        break;
      }
      used += width;
    }

    if (overflowIndex < items.length) {
      used = 0;
      const available = Math.max(containerWidth - moreButtonWidth, 0);
      overflowIndex = items.length;
      for (let index = 0; index < items.length; index += 1) {
        const width = items[index].measuredWidth;
        if (used + width > available) {
          overflowIndex = index;
          break;
        }
        used += width;
      }
    }

    const hasOverflow = overflowIndex < items.length;

    items.forEach((item, index) => {
      const isOverflow = index >= overflowIndex;
      item.anchor.hidden = isOverflow;
      item.overflowBtn.hidden = !isOverflow;
    });

    overflowToggle.hidden = !hasOverflow;
    overflowContainer.classList.toggle('tabs__overflow--hidden', !hasOverflow);
    if (!hasOverflow) {
      closeOverflowMenu();
    }
  }

  const debouncedLayout = debounce(applyPriorityLayout, 120);

  const handleResize = () => {
    closeOverflowMenu();
    debouncedLayout();
  };
  const handleOrientationChange = () => {
    closeOverflowMenu();
    debouncedLayout();
  };
  window.addEventListener('resize', handleResize);
  registerCleanup(() => window.removeEventListener('resize', handleResize));
  window.addEventListener('orientationchange', handleOrientationChange);
  registerCleanup(() => window.removeEventListener('orientationchange', handleOrientationChange));
  const rafId = window.requestAnimationFrame(() => {
    applyPriorityLayout();
  });
  registerCleanup(() => {
    if (typeof window.cancelAnimationFrame === 'function') {
      window.cancelAnimationFrame(rafId);
    }
  });

  function setActiveTab(tabId) {
    const normalized = typeof tabId === 'string' && tabId ? tabId : null;
    const brand = brandLink || header.querySelector('.brand');
    if (brand) {
      if (normalized) {
        brand.removeAttribute('aria-current');
      } else {
        brand.setAttribute('aria-current', 'page');
      }
    }
    items.forEach((item) => {
      const isActive = normalized === item.id;
      if (isActive) {
        item.anchor.setAttribute('aria-current', 'page');
        item.anchor.classList.add('is-active');
        item.overflowBtn.setAttribute('aria-current', 'page');
        item.overflowBtn.classList.add('is-active');
      } else {
        item.anchor.removeAttribute('aria-current');
        item.anchor.classList.remove('is-active');
        item.overflowBtn.removeAttribute('aria-current');
        item.overflowBtn.classList.remove('is-active');
      }
    });
  }

  closeOverflowMenu();
  setActiveTab(null);

  const controller = {
    setActiveTab,
    refreshLayout: applyPriorityLayout,
    elements: {
      diagnosticsToggle: header.querySelector('#btnDiagnostics') || header.querySelector('[data-action="toggle-diagnostics"]'),
      themeToggle: header.querySelector('#btnTheme'),
      refreshPatients:
        header.querySelector('#btnPatientsRefresh') || header.querySelector('[data-action="refresh-patients"]'),
    },
    closeOverflowMenu,
    destroy() {
      closeOverflowMenu();
      while (cleanupFns.length > 0) {
        const fn = cleanupFns.pop();
        try {
          fn();
        } catch (error) {
          console.debug('[header] cleanup callback failed', error);
        }
      }
      document[ACTIVE_HEADER_KEY] = null;
    },
  };

  document[ACTIVE_HEADER_KEY] = controller;

  return controller;
}
