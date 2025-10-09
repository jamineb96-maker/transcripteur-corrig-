// Petit état global observable.

const state = {};
const subscribers = {};

/**
 * Récupère la valeur d'un champ de l'état.
 *
 * @param {string} key Nom de la clé à lire
 * @returns {*} Valeur enregistrée ou undefined
 */
export function get(key) {
  return state[key];
}

/**
 * Modifie la valeur d'un champ de l'état et notifie les abonnés.
 *
 * @param {string} key Nom de la clé à modifier
 * @param {*} value Nouvelle valeur
 */
export function set(key, value) {
  const oldValue = state[key];
  state[key] = value;
  if (subscribers[key]) {
    subscribers[key].forEach((cb) => {
      try {
        cb(value, oldValue);
      } catch (e) {
        // Ignore les erreurs dans les callbacks pour éviter de bloquer d'autres notifications
      }
    });
  }
}

/**
 * S'abonne aux modifications d'une clé.
 *
 * @param {string} key Clé observée
 * @param {Function} callback Fonction appelée avec la nouvelle et l'ancienne valeur
 * @returns {Function} Fonction de désabonnement
 */
export function subscribe(key, callback) {
  if (!subscribers[key]) {
    subscribers[key] = [];
  }
  subscribers[key].push(callback);
  return () => {
    subscribers[key] = subscribers[key].filter((fn) => fn !== callback);
  };
}