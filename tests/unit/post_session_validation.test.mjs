import assert from 'node:assert/strict';
import { __test__ as postSessionTests } from '../../client/tabs/post_session/index.js';

const { validateAudioFile, MAX_AUDIO_SIZE } = postSessionTests;

const baseFile = {
  name: 'session.mp3',
  type: 'audio/mpeg',
  size: 1024 * 1024,
};

assert.deepEqual(
  validateAudioFile(baseFile),
  { ok: true },
  'An accepted audio file should pass validation',
);

const oversized = { ...baseFile, size: MAX_AUDIO_SIZE + 1 };
const sizeCheck = validateAudioFile(oversized);
assert.equal(sizeCheck.ok, false, 'File larger than the maximum size should be rejected');
assert.match(
  sizeCheck.error,
  /50 Mo/,
  'Size error message should mention the 50 Mo limit',
);

const wrongType = { name: 'notes.txt', type: 'text/plain', size: 1024 };
const typeCheck = validateAudioFile(wrongType);
assert.equal(typeCheck.ok, false, 'A non-audio file should be rejected');
assert.match(
  typeCheck.error,
  /Format non pris en charge/i,
  'Type error message should mention unsupported format',
);

console.log('post-session validation tests passed');
