const RAW_TABS = [
  { id: 'pre_session', idLegacy: ['pre-session'], name: 'Pré-séance', entry: 'tabs/pre_session/index.js' },
  { id: 'post_session', name: 'Post-séance', entry: 'tabs/post_session/index.js' },
  { id: 'journal_critique', name: 'Journal critique', entry: 'tabs/journal_critique/index.js' },
  { id: 'documents_aide', name: "Documents d’aide", entry: 'tabs/documents_aide/index.js' },
  { id: 'library', name: 'Bibliothèque', entry: 'tabs/library/index.js' },
  { id: 'constellation', name: 'Constellation', entry: 'tabs/constellation/index.js' },
  { id: 'anatomie3d', name: 'Anatomie 3D', entry: 'tabs/anatomy3d/index.js' },
  { id: 'facturation', name: 'Facturation', entry: 'tabs/facturation/index.js' },
  { id: 'agenda', name: 'Agenda', entry: 'tabs/agenda/index.js' },
  { id: 'budget', name: 'Budget', entry: 'tabs/budget/index.js' },
];

const TABS = Object.freeze(
  RAW_TABS.map((tab) => {
    const normalised = { ...tab };
    if (Array.isArray(normalised.idLegacy)) {
      normalised.idLegacy = [...normalised.idLegacy];
    }
    return Object.freeze(normalised);
  }),
);

const TAB_MAP = new Map(TABS.map((tab) => [tab.id, tab]));

function cloneTab(tab) {
  if (!tab) {
    return null;
  }
  const copy = { ...tab };
  if (Array.isArray(copy.idLegacy)) {
    copy.idLegacy = [...copy.idLegacy];
  }
  return copy;
}

export function listTabs() {
  return TABS.map((tab) => cloneTab(tab));
}

export function getTabInfo(tabId) {
  if (!tabId) {
    return null;
  }
  const info = TAB_MAP.get(tabId);
  if (info) {
    return cloneTab(info);
  }
  for (const tab of TABS) {
    if (!Array.isArray(tab.idLegacy)) {
      continue;
    }
    if (tab.idLegacy.includes(tabId)) {
      return cloneTab(tab);
    }
  }
  return null;
}

export function getTabEntry(tabId) {
  const info = getTabInfo(tabId);
  return info ? info.entry : null;
}

export function isValidTab(tabId) {
  return Boolean(getTabInfo(tabId));
}
