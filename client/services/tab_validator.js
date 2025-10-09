import { withAssetVersion } from './assets.js';
import { normalizeAssetUrl } from './asset_urls.js';

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '0.0.0.0']);

function isDevelopmentEnvironment() {
  if (typeof document !== 'undefined') {
    const debugAttr = document.body?.dataset?.debug;
    if (debugAttr === 'true') {
      return true;
    }
    if (debugAttr === 'false') {
      return false;
    }
  }
  if (typeof window !== 'undefined') {
    if (window.APP_DEBUG === true || window.APP_DEBUG === 'true') {
      return true;
    }
    const host = window.location?.hostname;
    if (host && LOCAL_HOSTS.has(host)) {
      return true;
    }
  }
  return false;
}

async function verifyAsset(url) {
  if (typeof fetch !== 'function') {
    return { ok: false, reason: 'fetch unavailable' };
  }
  const resolved = normalizeAssetUrl(withAssetVersion(url));
  try {
    let response = await fetch(resolved, { method: 'HEAD', cache: 'no-store' });
    if (response.ok) {
      return { ok: true };
    }
    if (response.status === 405 || response.status === 501) {
      response = await fetch(resolved, { cache: 'no-store' });
      return { ok: response.ok, reason: `HTTP ${response.status}` };
    }
    return { ok: false, reason: `HTTP ${response.status}` };
  } catch (error) {
    return { ok: false, reason: error instanceof Error ? error.message : String(error) };
  }
}

export async function validateTab(tabKey, options = {}) {
  const { assets = [], selectors = [] } = options;
  const result = {
    missingAssets: [],
    missingSelectors: [],
    duplicates: [],
    ran: false,
  };
  if (!isDevelopmentEnvironment()) {
    return result;
  }
  result.ran = true;
  const assetChecks = await Promise.all(
    assets.map(async (asset) => {
      const check = await verifyAsset(asset);
      return { asset, check };
    }),
  );
  assetChecks.forEach(({ asset, check }) => {
    if (!check.ok) {
      result.missingAssets.push({ url: asset, reason: check.reason || 'inconnu' });
    }
  });
  selectors.forEach((selector) => {
    if (!document.querySelector(selector)) {
      result.missingSelectors.push(selector);
    }
  });
  const duplicates = Array.isArray(window.__TAB_DUPLICATES__) ? window.__TAB_DUPLICATES__ : [];
  if (duplicates.includes(tabKey)) {
    result.duplicates.push(tabKey);
  }
  if (result.missingAssets.length || result.missingSelectors.length || result.duplicates.length) {
    console.warn('[tabs] Validation du module %s en échec', tabKey, result);
  } else {
    console.info('[tabs] Validation du module %s réussie', tabKey);
  }
  return result;
}
