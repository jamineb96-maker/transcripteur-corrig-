
// Minimal dark mode initializer (idempotent)
(function(){
  if (window.__THEME_OK__) return;
  function apply(mode){
    var sys = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    var isDark = mode === 'dark' || (mode === 'system' && sys);
    document.documentElement.classList.toggle('dark', !!isDark);
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    window.__THEME_MODE__ = mode;
  }
  var saved = localStorage.getItem('theme') || 'system';
  apply(saved);
  try {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(){ if ((localStorage.getItem('theme')||'system')==='system'){ apply('system'); }});
  } catch(e){}
  window.setTheme = function(mode){ try{ localStorage.setItem('theme', mode); }catch(e){}; apply(mode); };
  window.__THEME_OK__ = true;
})();