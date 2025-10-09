// Abstraction minimale de l'accès à localStorage avec sérialisation JSON.

/**
 * Lit une valeur JSON à partir de localStorage.
 *
 * @param {string} key Clé de stockage
 * @returns {*} Valeur désérialisée ou null si absente
 */
export function get(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

/**
 * Enregistre une valeur JSON dans localStorage.
 *
 * @param {string} key Clé sous laquelle stocker la valeur
 * @param {*} value Valeur à sérialiser
 */
export function set(key, value) {
  try {
    const raw = JSON.stringify(value);
    localStorage.setItem(key, raw);
  } catch (e) {
    // ignore
  }
}

/**
 * Supprime une entrée de localStorage.
 *
 * @param {string} key Clé à supprimer
 */
export function remove(key) {
  try {
    localStorage.removeItem(key);
  } catch (e) {
    // ignore
  }
}