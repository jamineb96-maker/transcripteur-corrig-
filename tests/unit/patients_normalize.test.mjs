import assert from 'node:assert/strict';
import { normalizePatients } from '../../client/services/patients.js';

const [normalized] = normalizePatients([{ name: 'Zoé' }]);

assert.ok(normalized, 'normalizePatients should return an object');
assert.equal(normalized.id, 'zoe', 'Should slugify name with accents to build id');
assert.equal(normalized.displayName, 'Zoé', 'Should keep the original name as displayName');
assert.equal(normalized.name, 'Zoé', 'Should populate name field');
assert.equal(normalized.full_name, 'Zoé', 'Should propagate full_name from name when missing');
assert.equal(normalized.email, '', 'Should provide empty string for missing email');

console.log('normalizePatients basic test passed');
