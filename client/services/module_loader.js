import { normalizeAssetUrl } from './asset_urls.js';

const moduleCache = new Map();

export async function safeDynamicImport(entry, options = {}) {
  const { cacheKey, forceReload = false } = options;

  try {
    if (!entry || typeof entry !== 'string') {
      throw new Error(`Entrée de module invalide : ${entry}`);
    }

    const normalizedUrl = normalizeAssetUrl(entry);
    const key = cacheKey || normalizedUrl;

    if (forceReload) {
      moduleCache.delete(key);
    } else if (moduleCache.has(key)) {
      return moduleCache.get(key);
    }

    const importPromise = import(/* @vite-ignore */ normalizedUrl)
      .then((mod) => mod ?? null)
      .catch((error) => {
        moduleCache.delete(key);
        throw error;
      });

    moduleCache.set(key, importPromise);
    return await importPromise;
  } catch (e) {
    console.error('[tab-import-failed]', entry, e); // eslint-disable-line no-console
    return null;
  }
}

export function __resetModuleLoaderCache() {
  moduleCache.clear();
}
