
// Minimal tabs bootstrap: populates primary nav and ensures panels exist.
(function(){
  if (window.__TABS_BOOTSTRAPPED__) return;
  function $(sel){ return document.querySelector(sel); }
  function $all(sel){ try { return Array.prototype.slice.call(document.querySelectorAll(sel)||[]); } catch(e){ return []; } }

  // Derive candidate tabs from existing links (#post_session etc.) or fallback to a known list
  var anchors = $all('a[href^="#"]');
  var names = anchors.map(a => (a.getAttribute('href')||'').replace(/^#/, '')).filter(Boolean);
  var KNOWN = ["home","pre_session","post_session","documents_aide","journal_critique","facturation","agenda","constellation","anatomie3d","budget"];
  names = Array.from(new Set(names.concat(KNOWN))).filter(Boolean);

  // Inject buttons into primary nav if empty
  var nav = document.querySelector('nav.primary-nav[data-nav="primary"]');
  if (nav && !nav.children.length) {
    var frag = document.createDocumentFragment();
    names.forEach(function(name){
      if (!name) return;
      var a = document.createElement('a');
      a.setAttribute('href', '#'+name);
      a.setAttribute('data-nav','');
      a.textContent = name.replace(/_/g,' ').replace(/\b\w/g, c => c.toUpperCase());
      frag.appendChild(a);
    });
    nav.appendChild(frag);
  }

  // Ensure a container exists for each panel we can show
  var root =
    document.querySelector('[data-tab-root]') ||
    document.getElementById('app') ||
    document.querySelector('[data-panels-root]') ||
    document.body;
  function ensurePanel(name){
    name = (name||'').toLowerCase();
    if (!name || name === 'home') {
      return document.getElementById('tab-home');
    }
    var byId = document.getElementById('tab-'+name);
    if (byId) return byId;
    var byData = document.querySelector('[data-tab="'+name+'"]');
    if (byData) return byData;
    var panel = document.createElement('section');
    panel.id = 'tab-'+name;
    panel.className = 'tab-panel';
    panel.setAttribute('data-name', name);
    panel.setAttribute('data-tab', name);
    panel.setAttribute('hidden','');
    panel.innerHTML = '<div class="panel__inner"><h2>'+name.replace(/_/g,' ')+'</h2><div class="panel__body" data-panel-body="'+name+'">Chargement…</div></div>';
    root.appendChild(panel);
    // Special minimal scaffolding for post_session expected UI
    if (name === 'post_session') {
      var body = panel.querySelector('[data-panel-body="post_session"]');
      if (body) {
        body.innerHTML = ''
          + '<p><strong>Durée détectée:</strong> <span data-duration>—</span></p>'
          + '<p><strong>Idempotency key:</strong> <span data-idem>—</span></p>'
          + '<div class="progress" aria-label="Progression par chunks"><div class="progress__bar" style="width:0%"></div></div>'
          + '<p><a href="#" data-action="resume">Reprendre au dernier état</a> | <a href="#" data-action="textonly">Mode texte-seul</a></p>'
          + '<div class="mail-preview" data-mail-preview>Prévisualisation du mail…</div>';
      }
    }
    return panel;
  }

  // Create panels for discovered names (but keep hidden initially)
  names.forEach(ensurePanel);

  window.__ensurePanel = ensurePanel;
  window.__TABS_BOOTSTRAPPED__ = true;
})();