// Minimal dark mode initializer (idempotent)
(function () {
  if (window.__THEME_OK__) return;

  function apply(mode) {
    var systemPrefersDark =
      window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches;
    var isDark = mode === 'dark' || (mode === 'system' && systemPrefersDark);

    document.documentElement.classList.toggle('dark', !!isDark);
    document.documentElement.setAttribute(
      'data-theme',
      isDark ? 'dark' : 'light'
    );
    window.__THEME_MODE__ = mode;
  }

  var saved = localStorage.getItem('theme') || 'system';
  apply(saved);

  try {
    var media = window.matchMedia('(prefers-color-scheme: dark)');
    if (media && media.addEventListener) {
      media.addEventListener('change', function () {
        if ((localStorage.getItem('theme') || 'system') === 'system') {
          apply('system');
        }
      });
    }
  } catch (error) {
    console.warn('Unable to bind prefers-color-scheme listener', error);
  }

  window.setTheme = function (mode) {
    try {
      localStorage.setItem('theme', mode);
    } catch (error) {
      console.warn('Unable to persist theme preference', error);
    }
    apply(mode);
  };

  window.__THEME_OK__ = true;
})();
