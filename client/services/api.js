// Fonctions utilitaires pour effectuer des requêtes JSON auprès du serveur.

export const API_BASE = typeof window !== 'undefined' ? window.__API_BASE__ || '' : '';

async function handleResponse(response) {
  const contentType = response.headers.get('Content-Type') || '';
  let data;
  if (contentType.includes('application/json')) {
    data = await response.json();
  } else {
    data = await response.text();
  }
  const extractMessage = (payload) => {
    if (!payload || typeof payload !== 'object') {
      return null;
    }
    if (payload.error) {
      if (typeof payload.error === 'string') {
        return payload.error;
      }
      if (payload.error.message) {
        return payload.error.message;
      }
    }
    if (payload.message) {
      return payload.message;
    }
    return null;
  };

  if (!response.ok || (data && typeof data === 'object' && data.success === false)) {
    const message = extractMessage(data) || response.statusText || 'Une erreur est survenue.';
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

/**
 * Effectue une requête GET et renvoie du JSON.
 *
 * @param {string} url Chemin relatif à appeler
 */
export async function jsonGet(url) {
  const resp = await fetch(`${API_BASE}${url}`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
    },
  });
  return handleResponse(resp);
}

/**
 * Effectue une requête POST avec un corps JSON et renvoie la réponse JSON.
 *
 * @param {string} url Chemin relatif à appeler
 * @param {*} body Corps de la requête à sérialiser
 */
export async function jsonPost(url, body) {
  const resp = await fetch(`${API_BASE}${url}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(body || {}),
  });
  return handleResponse(resp);
}

export async function jsonDelete(url) {
  const resp = await fetch(`${API_BASE}${url}`, {
    method: 'DELETE',
    headers: {
      Accept: 'application/json',
    },
  });
  return handleResponse(resp);
}