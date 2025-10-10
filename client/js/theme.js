/*
 * Gestion du thème (clair/sombre/système) pour l'assistant clinique.
 *
 * Ce module lit la préférence enregistrée dans localStorage et, à défaut,
 * s'adapte au système via la media query « prefers-color-scheme ».  Il
 * applique à la fois une classe « dark » sur <html> et un attribut
 * « data-theme="dark" » pour assurer la compatibilité ascendante avec les
 * sélecteurs existants.  Une fonction globale setTheme() est exposée
 * permettant de forcer un mode précis (« light », « dark » ou « system »).
 */

(() => {
  const STORAGE_KEY = 'theme';

  /**
   * Applique le thème en fonction du mode souhaité.  En mode « system »,
   * l'état de la media query est utilisé.  Le thème sombre est activé si
   * isDark vaut true.
   * @param {string|'light'|'dark'|'system'} mode
   */
  function applyTheme(mode) {
    let isDark;
    if (mode === 'dark') {
      isDark = true;
    } else if (mode === 'light') {
      isDark = false;
    } else {
      // mode système : interroger prefers-color-scheme
      isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    }
    try {
      const root = document.documentElement;
      root.classList.toggle('dark', !!isDark);
      root.setAttribute('data-theme', isDark ? 'dark' : 'light');
    } catch (_err) {
      /* ignore */
    }
  }

  /**
   * Définit le thème persistant et l'applique immédiatement.
   * @param {'light'|'dark'|'system'} theme
   */
  function setTheme(theme) {
    try {
      if (typeof theme === 'string') {
        localStorage.setItem(STORAGE_KEY, theme);
      }
    } catch (_err) {
      /* ignore storage errors */
    }
    applyTheme(theme);
  }

  /**
   * Initialise la logique thème : lecture de la valeur enregistrée, écoute
   * des changements système et exposition de l'API globale.
   */
  function initTheme() {
    let saved;
    try {
      saved = localStorage.getItem(STORAGE_KEY);
    } catch (_err) {
      saved = null;
    }
    // valeur par défaut : système
    const initial = saved || 'system';
    applyTheme(initial);

    // Actualise le thème lorsque la préférence système change si l'utilisateur
    // n'a pas choisi explicitement un mode.
    if (window.matchMedia) {
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      mq.addEventListener('change', () => {
        let current;
        try {
          current = localStorage.getItem(STORAGE_KEY);
        } catch (_err) {
          current = null;
        }
        if (!current || current === 'system') {
          applyTheme('system');
        }
      });
    }
    // Expose la fonction globalement pour les tests et les boutons
    window.setTheme = setTheme;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTheme, { once: true });
  } else {
    initTheme();
  }
})();