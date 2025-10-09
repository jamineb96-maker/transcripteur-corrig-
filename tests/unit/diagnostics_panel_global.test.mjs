import assert from 'node:assert/strict';

globalThis.window = {
  location: { origin: 'http://localhost:5000' },
};

globalThis.document = {
  querySelector: () => null,
  body: {
    classList: {
      toggle: () => {},
    },
  },
};

const { initDiagnosticsPanel } = await import('../../client/components/diagnostics_panel.js');

initDiagnosticsPanel();

assert.equal(typeof window.__diag, 'object', 'window.__diag should be exposed');
assert.equal(typeof window.__diag.show, 'function', 'window.__diag.show should be a function');
assert.equal(typeof window.__diag.hide, 'function', 'window.__diag.hide should be a function');

window.__diag.show();
window.__diag.hide();

console.log('Diagnostics panel global handle test passed');
