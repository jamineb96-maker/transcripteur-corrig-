/*
 * Routeur SPA tolérant pour l'assistant clinique.
 *
 * Cette implémentation ne modifie pas les routes existantes et ne dépend
 * d'aucune bibliothèque externe.  Elle est idempotente : si le routeur a
 * déjà été initialisé (via la variable globale __APP_OK), il ne se
 * réinitialisera pas.  Le routeur prend en charge différents schémas
 * d'URL : ancre (ex. « #post_session »), paramètre de requête (ex.
 * « ?tab=post_session ») ou segment d'URL (ex. « /tab/post_session »).  Il
 * met à jour l'attribut data-active-tab sur <body> pour permettre aux
 * modules dynamiques de réagir et applique la classe « active » sur les
 * liens de navigation correspondants.
 */

(() => {
  // Ne démarre qu'une seule fois
  if (window.__APP_OK) return;

  /**
   * Sélecteur sécurisé retournant toujours un tableau vide en cas d'erreur.
   * @param {string} sel
   * @returns {Array<Element>}
   */
  function $all(sel) {
    try {
      return Array.from(document.querySelectorAll(sel));
    } catch (_err) {
      return [];
    }
  }

  /**
   * Détermine le nom de l'onglet à partir de l'URL courante.  Priorité à
   * l'argument de requête « tab », ensuite au chemin « /tab/… », puis à
   * l'ancre.  Retourne « home » par défaut.
   * @returns {string}
   */
  function getTabFromURL() {
    try {
      const url = new URL(window.location.href);
      const q = (url.searchParams.get('tab') || '').trim();
      if (q) return q.toLowerCase();
      const path = url.pathname || '';
      if (path.toLowerCase().startsWith('/tab/')) {
        return path.split('/').pop().toLowerCase();
      }
    } catch (_err) {
      /* noop */
    }
    const hash = window.location.hash;
    if (hash && hash.startsWith('#') && hash.length > 1) {
      return hash.slice(1).toLowerCase();
    }
    return 'home';
  }

  /**
   * Affiche l'onglet demandé et met à jour l'état actif des panneaux et des
   * liens.  Si aucun panneau n'est trouvé via data-tab, .tab-panel ou id
   * commençant par « tab- », l'appel basculera uniquement l'état du panneau
   * d'accueil via data-active-tab.
   * @param {string} name
   */
  function showTab(name) {
    const tabName = (name || 'home').toLowerCase();
    // Propager l'état sur <body> pour les composants réactifs
    try {
      document.body.setAttribute('data-active-tab', tabName);
    } catch (_err) {
      /* ignore */
    }

    // Sélectionner tous les panneaux possibles
    const panels = $all('[data-tab], .tab-panel, [id^="tab-"]');
    if (panels.length) {
      panels.forEach((el) => {
        // Détermine la clef du panneau : data-tab, data-name ou id
        let key = '';
        const dt = el.getAttribute('data-tab');
        if (dt) key = dt.toLowerCase();
        else if (el.classList.contains('tab-panel')) {
          const dn = el.getAttribute('data-name');
          if (dn) key = dn.toLowerCase();
        } else if (el.id && el.id.toLowerCase().startsWith('tab-')) {
          key = el.id.slice(4).toLowerCase();
        }
        const active = key === tabName;
        // Utilise style.display et l'attribut hidden pour masquer/afficher
        if (active) {
          el.style.display = '';
          if (el.toggleAttribute) el.toggleAttribute('hidden', false);
        } else {
          el.style.display = 'none';
          if (el.toggleAttribute) el.toggleAttribute('hidden', true);
        }
      });
    }
    // Masquer explicitement l'accueil si l'onglet n'est pas home
    if (tabName !== 'home') {
      const homeEl = document.getElementById('tab-home') || document.querySelector('[data-tab="home"]') || document.querySelector('.home, .home-root');
      if (homeEl) {
        homeEl.style.display = 'none';
        homeEl.setAttribute('hidden', '');
      }
    }
    // Mettre à jour l'état actif des liens de navigation
    $all('a[data-nav], nav a, .sidebar a, a[data-tab-link]').forEach((a) => {
      try {
        const href = a.getAttribute('href') || '';
        let want = '';
        if (href.includes('?tab=')) {
          const u = new URL(href, window.location.origin);
          want = (u.searchParams.get('tab') || '').toLowerCase();
        } else if (href.toLowerCase().startsWith('/tab/')) {
          want = href.split('/').pop().toLowerCase();
        } else if (href.startsWith('#')) {
          want = href.replace(/^#/, '').toLowerCase();
        }
        a.classList.toggle('active', want === tabName);
      } catch (_err) {
        /* ignore */
      }
    });
  }

  /**
   * Logique principale de routage : déterminer l'onglet et l'afficher.
   */
  function route() {
    try {
      const current = getTabFromURL();
      showTab(current);
    } catch (err) {
      console.error(err);
    }
  }

  /**
   * Initialise le routeur en interceptant les clics et en réagissant aux
   * changements de l'historique.
   */
  function initRouter() {
    document.body.addEventListener(
      'click',
      (event) => {
        const target = event.target;
        if (!target) return;
        const a = target.closest ? target.closest('a') : null;
        if (!a) return;
        const href = a.getAttribute('href') || '';
        // Ignore les liens externes (http, https, mailto, tel)
        if (!href || /^https?:/i.test(href) || href.startsWith('mailto:') || href.startsWith('tel:')) return;
        // Détecte les navigations internes pertinentes
        const isTabNav = href.includes('?tab=') || href.startsWith('#') || href.toLowerCase().startsWith('/tab/');
        if (isTabNav) {
          event.preventDefault();
          history.pushState({}, '', href);
          route();
        }
      },
      true,
    );
    window.addEventListener('popstate', route);
    route();
    window.__APP_OK = true;
    console.log('SPA router initialisé');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initRouter, { once: true });
  } else {
    initRouter();
  }
})();