// Normalise une URL d'asset statique sans double préfixer /static.
// - Préserve les URL absolues (http, https, file, data, etc.)
// - Préserve les URLs déjà enracinées (/...)
// - Conserve la query (?v=...)
// - Préserve les chemins relatifs explicites (./, ../)
// - Préfixe les chemins nus avec /static/

const PROTOCOL_REGEX = /^[a-zA-Z][a-zA-Z0-9+.-]*:/;

export function normalizeAssetUrl(input) {
  if (!input || typeof input !== 'string') {
    return '';
  }

  const trimmed = input.trim();
  if (!trimmed) {
    return '';
  }

  if (trimmed.startsWith('//')) {
    return trimmed;
  }

  if (PROTOCOL_REGEX.test(trimmed)) {
    return trimmed;
  }

  if (trimmed.startsWith('/')) {
    return trimmed;
  }

  if (trimmed.startsWith('./') || trimmed.startsWith('../')) {
    return trimmed;
  }

  const [path, query = ''] = trimmed.split('?');
  const cleanPath = path.replace(/^\/+/u, '');
  const url = `/static/${cleanPath}`;
  return query ? `${url}?${query}` : url;
}

export default normalizeAssetUrl;
