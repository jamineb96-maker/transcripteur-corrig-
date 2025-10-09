/*
 * Panneau de recherche de ressources partagé pour les onglets pré/post.
 *
 * Ce module exporte les fonctions `mount(container, { tab })` et
 * `unmount()`.  Lorsqu'il est monté dans un conteneur DOM, il crée
 * dynamiquement un champ de recherche, affiche les résultats et
 * permet d'ouvrir une ressource pour en consulter le contenu.  Aucun
 * module externe n'est requis, la communication se fait via les
 * endpoints `/api/library/*`.
 */

import { jsonGet } from '../services/api.js';

let rootEl = null;

/**
 * Monte le panneau dans un conteneur spécifié.
 *
 * @param {HTMLElement} container Élément DOM dans lequel monter le panneau
 * @param {Object} options Options (actuellement inutilisées, réservé à l'avenir)
 */
export function mount(container, options = {}) {
  if (rootEl) return;
  // Création de l'élément racine
  rootEl = document.createElement('div');
  rootEl.classList.add('resources-panel', 'panel');
  rootEl.innerHTML = `
    <div class="resources-search">
      <input type="text" data-field="search" placeholder="Rechercher une ressource..." />
      <button type="button" data-action="search" class="ghost">Rechercher</button>
    </div>
    <div class="resources-results"></div>
    <div class="resources-viewer hidden">
      <div class="resource-content"></div>
      <div style="text-align:right;margin-top:8px;">
        <button type="button" data-action="close" class="ghost">Fermer</button>
      </div>
    </div>
  `;
  container.appendChild(rootEl);
  // Écouteurs pour les actions et la saisie
  rootEl.addEventListener('click', handleClick);
  rootEl.addEventListener('keyup', handleKeyUp);

  // Injection de la feuille de style spécifique si nécessaire
  const styleHref = `/static/components/resources_panel.css?v=${window.ASSET_VERSION}`;
  if (!document.querySelector(`link[href="${styleHref}"]`)) {
    const linkEl = document.createElement('link');
    linkEl.rel = 'stylesheet';
    linkEl.href = styleHref;
    document.head.appendChild(linkEl);
  }
}

/**
 * Détache le panneau du DOM et nettoie les écouteurs.
 */
export function unmount() {
  if (!rootEl) return;
  rootEl.removeEventListener('click', handleClick);
  rootEl.removeEventListener('keyup', handleKeyUp);
  if (rootEl.parentNode) {
    rootEl.parentNode.removeChild(rootEl);
  }
  rootEl = null;
}

// Gestionnaire de clics sur le panneau
async function handleClick(event) {
  const action = event.target && event.target.dataset && event.target.dataset.action;
  if (!action) return;
  switch (action) {
    case 'search':
      await performSearch();
      break;
    case 'open': {
      const id = event.target.dataset.id;
      if (id) await openItem(id);
      break;
    }
    case 'close':
      closeItem();
      break;
    default:
      break;
  }
}

// Gestionnaire de la touche Entrée dans le champ de recherche
async function handleKeyUp(event) {
  if (event.target && event.target.dataset && event.target.dataset.field === 'search' && event.key === 'Enter') {
    await performSearch();
  }
}

// Exécute la recherche via l'API
async function performSearch() {
  if (!rootEl) return;
  const input = rootEl.querySelector('input[data-field="search"]');
  const query = input ? input.value.trim() : '';
  const resultsEl = rootEl.querySelector('.resources-results');
  if (!query) {
    if (resultsEl) resultsEl.innerHTML = '';
    return;
  }
  if (resultsEl) resultsEl.innerHTML = '<p>Recherche…</p>';
  try {
    const resp = await jsonGet(`/api/library/search?q=${encodeURIComponent(query)}`);
    const items = (resp && resp.data) || [];
    if (resultsEl) resultsEl.innerHTML = '';
    if (!items.length) {
      if (resultsEl) resultsEl.innerHTML = '<p>Aucun résultat.</p>';
      return;
    }
    items.forEach((item) => {
      const card = document.createElement('div');
      card.className = 'resource-card';
      card.innerHTML = `
        <h4>${item.title}</h4>
        <p>${item.summary}</p>
        <button type="button" data-action="open" data-id="${item.id}" class="ghost">Ouvrir</button>
      `;
      resultsEl.appendChild(card);
    });
  } catch (e) {
    console.error('Erreur lors de la recherche de ressources', e);
    if (resultsEl) resultsEl.innerHTML = '<p>Erreur lors de la recherche.</p>';
  }
}

// Ouvre un élément en affichant son contenu
async function openItem(id) {
  if (!rootEl) return;
  const viewer = rootEl.querySelector('.resources-viewer');
  const contentEl = rootEl.querySelector('.resource-content');
  if (viewer && contentEl) {
    viewer.classList.remove('hidden');
    contentEl.innerHTML = '<p>Chargement…</p>';
  }
  try {
    const resp = await jsonGet(`/api/library/item?id=${encodeURIComponent(id)}`);
    const data = resp && resp.data;
    if (data && contentEl) {
      // Sécurise l'affichage en échappant le contenu
      const esc = (s) => {
        const div = document.createElement('div');
        div.textContent = s;
        return div.innerHTML;
      };
      contentEl.innerHTML = `<h4>${esc(data.title)}</h4><pre>${esc(data.content)}</pre>`;
    } else if (contentEl) {
      contentEl.innerHTML = '<p>Document non trouvé.</p>';
    }
  } catch (e) {
    console.error('Erreur lors de la récupération de la ressource', e);
    if (contentEl) contentEl.innerHTML = '<p>Erreur de chargement.</p>';
  }
}

// Ferme la vue détaillée d'une ressource
function closeItem() {
  if (!rootEl) return;
  const viewer = rootEl.querySelector('.resources-viewer');
  if (viewer) viewer.classList.add('hidden');
}