import assert from 'node:assert/strict';

import { getTabEntry, isValidTab, listTabs } from '../../client/services/tabs_registry.js';

const tabs = listTabs();
assert.ok(Array.isArray(tabs), 'listTabs should return an array');
assert.ok(tabs.length > 0, 'listTabs should expose at least one tab');

for (const tab of tabs) {
  assert.equal(typeof tab.id, 'string', 'tab.id should be a string');
  assert.equal(typeof tab.name, 'string', 'tab.name should be a string');
  assert.equal(typeof tab.entry, 'string', 'tab.entry should be a string');
  assert.ok(tab.entry.startsWith('tabs/'), 'Entries should be relative to the static root');
}

const preSessionEntry = getTabEntry('pre_session');
assert.equal(
  preSessionEntry,
  'tabs/pre_session/index.js',
  'getTabEntry should return the canonical entry path',
);

const legacyPreSessionEntry = getTabEntry('pre-session');
assert.equal(
  legacyPreSessionEntry,
  'tabs/pre_session/index.js',
  'Legacy identifiers should map to the canonical entry path',
);

assert.equal(isValidTab('pre_session'), true, 'pre_session should be recognised as a valid tab');
assert.equal(isValidTab('unknown-tab'), false, 'Unknown tabs should not be valid');

if (tabs.length >= 1) {
  const first = tabs[0];
  first.entry = '/tampered.js';
  const [fresh] = listTabs();
  assert.notEqual(fresh.entry, '/tampered.js', 'listTabs should return defensive copies');
}

console.log('tabs_registry tests passed');
