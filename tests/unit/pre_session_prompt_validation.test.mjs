import assert from 'node:assert/strict';

globalThis.window = {
  __API_BASE__: '',
  addEventListener: () => {},
  alert: () => {},
};

const { __test__ } = await import('../../client/tabs/pre_session/index.js');

const { validatePromptText } = __test__;

const valid = validatePromptText('Le suivi thérapeutique peut commencer.');
assert.equal(valid.valid, true, 'Should accept prompts without forbidden content');

const withBraces = validatePromptText('Utiliser {SYSTEM} pour configurer.');
assert.equal(withBraces.valid, false, 'Should reject prompts containing braces');
assert.equal(withBraces.reason, 'forbidden_braces', 'Should indicate braces as the reason');

const withBannedTerm = validatePromptText('Ce patient présente un profil borderline.');
assert.equal(withBannedTerm.valid, false, 'Should reject prompts containing banned terminology');
assert.equal(withBannedTerm.reason, 'banned_language', 'Should indicate banned language as the reason');

console.log('All pre-session prompt validation tests passed');
