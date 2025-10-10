


// --- SPA router (robust, idempotent) ---
(function () {
  if (window.__APP_OK) return;
  function $all(sel){ try{ return document.querySelectorAll(sel) || []; }catch(e){ return []; } }
  function showTab(name) {
    name = (name||'home').toLowerCase();
    var panels = Array.prototype.slice.call($all('[data-tab], .tab-panel, [id^="tab-"]'));
    if (!panels.length) return;
    panels.forEach(function(el){
      var key =
        (el.getAttribute('data-tab')||'').toLowerCase() ||
        (el.classList.contains('tab-panel') && (el.getAttribute('data-name')||'').toLowerCase()) ||
        (el.id && el.id.toLowerCase().indexOf('tab-')===0 ? el.id.slice(4).toLowerCase() : '');
      var active = (key === name);
      el.style.display = active ? 'block' : 'none';
      if (el.toggleAttribute) el.toggleAttribute('hidden', !active);
    });
    if (name !== 'home') {
      var home = document.getElementById('tab-home') || document.querySelector('[data-tab="home"]') || document.querySelector('.home, .home-root');
      if (home) { home.style.display = 'none'; home.setAttribute('hidden',''); }
    }
    Array.prototype.slice.call($all('a[data-nav], nav a, .sidebar a')).forEach(function(a){
      try {
        var url = new URL(a.href, location.origin);
        var want = (url.searchParams.get('tab') || '').toLowerCase();
        if (!want && url.pathname.toLowerCase().indexOf('/tab/')===0) {
          want = url.pathname.split('/').pop().toLowerCase();
        }
        a.classList.toggle('active', want === name);
      } catch(e){}
    });
  }
  function getTabFromURL() {
    try {
      var url = new URL(location.href);
      var t = url.searchParams.get('tab');
      if (t) return t.toLowerCase();
      if (url.pathname.toLowerCase().indexOf('/tab/')===0) {
        return url.pathname.split('/').pop().toLowerCase();
      }
    } catch (e) {}
    if (location.hash && location.hash.indexOf('#')===0) {
      var h = location.hash.replace(/^#/, '');
      if (h) return h.toLowerCase();
    }
    return 'home';
  }
  function route(){ try{ showTab(getTabFromURL()); }catch(e){ console.error(e); } }
  function initRouter(){
    document.body.addEventListener('click', function(e){
      var a = e.target.closest && e.target.closest('a');
      if (!a) return;
      var href = a.getAttribute('href') || '';
      if (!href || /^https?:/i.test(href) || href.startsWith('mailto:') || href.startsWith('tel:')) return;
      if (href.indexOf('?tab=')>=0 || href.indexOf('#')===0 || href.indexOf('/tab/')===0) {
        e.preventDefault();
        history.pushState({}, '', href);
        route();
      }
    }, true);
    window.addEventListener('popstate', route);
    route();
    window.__APP_OK = true;
    console.log('SPA router booted');
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initRouter, {once:true});
  } else {
    initRouter();
  }
})();