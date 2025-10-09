// Utilitaires pour la version des assets statiques.

const meta = typeof document !== 'undefined' ? document.querySelector('meta[name="asset-version"]') : null;
const metaVersion = meta?.getAttribute('content')?.trim();

export const ASSET_VERSION = metaVersion || (typeof window !== 'undefined' ? window.ASSET_VERSION || '' : '');

if (typeof window !== 'undefined' && !window.ASSET_VERSION) {
  window.ASSET_VERSION = ASSET_VERSION;
}

export function withAssetVersion(url) {
  if (!url) {
    return url;
  }
  const version = ASSET_VERSION;
  if (!version) {
    return url;
  }
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}v=${encodeURIComponent(version)}`;
}

