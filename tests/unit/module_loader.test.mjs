import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import {
  safeDynamicImport,
  __resetModuleLoaderCache,
} from '../../client/services/module_loader.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const tempModulePath = path.join(__dirname, 'tmp_dynamic_module.mjs');
fs.writeFileSync(tempModulePath, 'export const answer = 42;\n');

const moduleUrl = pathToFileURL(tempModulePath).href;
__resetModuleLoaderCache();

const loadedModule = await safeDynamicImport(moduleUrl, { cacheKey: 'tmp-module' });
assert.equal(loadedModule?.answer, 42, 'Should import a valid module and expose its exports');

fs.unlinkSync(tempModulePath);

const failingModule = await safeDynamicImport('/__nonexistent__/module.mjs');
assert.equal(failingModule, null, 'Failed imports should return null');

const invalidEntry = await safeDynamicImport(null);
assert.equal(invalidEntry, null, 'Invalid entries should return null');

console.log('module_loader tests passed');
