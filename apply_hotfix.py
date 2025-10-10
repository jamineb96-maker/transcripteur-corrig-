#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hotfix: assets route + SPA router bootstrap + logo placeholder.

Usage (from your project root):
    python apply_hotfix.py

What it does:
1) Patches server/__init__.py to add a legacy `/assets/<path:filename>` route that serves from `/static/assets`.
2) Appends a robust, no-crash SPA router to `server/static/app.js` if not already present.
3) Installs a placeholder logo at `server/static/assets/logo.png` if missing.

Backups:
Creates `.bak` files before modifying anything.
"""
import sys, re, os, shutil, base64
from pathlib import Path

PROJECT_ROOT = Path.cwd()

def info(msg): print("[hotfix]", msg)
def warn(msg): print("[hotfix:warn]", msg)
def die(msg): 
    print("[hotfix:ERROR]", msg)
    sys.exit(1)

def patch_assets_route(server_init: Path):
    text = server_init.read_text(encoding="utf-8")
    # Make sure we're inside create_app and routes use @app.get
    if "def create_app(" not in text or "@app.get(\"/\")" not in text and "@app.route(\"/\")" not in text:
        warn("Could not confidently detect create_app or index route. Skipping assets route patch.")
        return False

    # Check if already present
    if "/assets/<path:filename>" in text:
        info("Assets legacy route already present, skipping.")
        return False

    # Insert route right after index_page() definition block.
    # Simpler: inject just before the line `return app` (end of create_app), keeping indentation.
    import re as _re
    m_end = _re.search(r'\n\s*return\s+app\s*\n', text)
    if not m_end:
        warn("Could not find `return app` inside create_app. Skipping assets route patch.")
        return False

    # Determine indentation inside create_app (assume 4 spaces block)
    indent = "    "
    route_block = f"""
{indent}@app.get("/assets/<path:filename>")
{indent}def legacy_assets(filename: str):
{indent}    \"\"\"Compatibility route: serve /assets/* from /static/assets/*.\"\"\"
{indent}    from flask import send_from_directory
{indent}    from pathlib import Path as _Path
{indent}    static_assets = _Path(app.static_folder) / "assets"
{indent}    target = static_assets / filename
{indent}    if target.exists() and target.is_file():
{indent}        return send_from_directory(str(static_assets), filename)
{indent}    return handle_error("Fichier introuvable.", 404)
"""

    new_text = text[:m_end.start()] + route_block + text[m_end.start():]
    # backup
    backup = server_init.with_suffix(server_init.suffix + ".bak")
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")
    server_init.write_text(new_text, encoding="utf-8")
    info(f"Patched assets route in {server_init}")
    return True

SPA_SNIPPET = r'''(function () {
  if (window.__APP_OK) return; // idempotent
  function showTab(name) {
    var panels = document.querySelectorAll('[data-tab]');
    if (!panels || !panels.length) return;
    for (var i=0; i<panels.length; i++) {
      var el = panels[i];
      el.style.display = (el.getAttribute('data-tab') === name) ? 'block' : 'none';
    }
    var links = document.querySelectorAll('a[data-nav]');
    for (var j=0; j<links.length; j++) {
      try {
        var a = links[j];
        var url = new URL(a.href, location.origin);
        var wants = (url.searchParams.get('tab') || '').toLowerCase();
        a.classList.toggle('active', wants === name);
      } catch (e) {}
    }
  }
  function getTabFromURL() {
    try {
      var url = new URL(location.href);
      var t = url.searchParams.get('tab');
      if (t) return t.toLowerCase();
    } catch (e) {}
    if (location.hash && location.hash.indexOf('#tab=') === 0) {
      return location.hash.slice(5).toLowerCase();
    }
    return 'home';
  }
  function route() {
    try { showTab(getTabFromURL()); } catch (e) { console.error('Routing error:', e); }
  }
  function initRouter() {
    document.body.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('a[data-nav]');
      if (!a) return;
      var href = a.getAttribute('href') || '';
      if (!href || /^https?:/i.test(href)) return;
      e.preventDefault();
      history.pushState({}, '', href);
      route();
    });
    window.addEventListener('popstate', route);
    route();
    window.__APP_OK = true;
    console.log('SPA router booted');
  }
  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', function(){ try { initRouter(); } catch(e){ console.error(e); } });
  } else {
    try { initRouter(); } catch(e){ console.error(e); }
  }
})();'''

def patch_app_js(app_js: Path):
    original = ""
    if app_js.exists():
        try:
            original = app_js.read_text(encoding="utf-8")
        except Exception:
            original = ""
    else:
        # create parent dirs if needed
        app_js.parent.mkdir(parents=True, exist_ok=True)
        original = ""

    # If our marker is present, skip
    if "SPA router booted" in original or "window.__APP_OK" in original:
        info("SPA router already present in app.js, skipping append.")
        return False

    backup = app_js.with_suffix(app_js.suffix + ".bak")
    if not backup.exists():
        backup.write_text(original, encoding="utf-8")
    new_text = (original.rstrip() + "\n\n// --- HOTFIX: robust SPA router ---\n" + SPA_SNIPPET + "\n")
    app_js.write_text(new_text, encoding="utf-8")
    info(f"Appended SPA router to {app_js}")
    return True

# 1x1 transparent PNG
LOGO_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/w8AAn8B9mQ3rDIAAAAASUVORK5CYII="
)

def ensure_logo(static_dir: Path):
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    logo = assets_dir / "logo.png"
    if logo.exists() and logo.stat().st_size > 0:
        info("Logo already present, skipping.")
        return False
    logo.write_bytes(base64.b64decode(LOGO_B64))
    info(f"Installed placeholder logo at {logo}")
    return True

def main():
    server_init = PROJECT_ROOT / "server" / "__init__.py"
    static_dir = PROJECT_ROOT / "server" / "static"
    app_js = static_dir / "app.js"

    if not server_init.exists():
        die("Could not find server/__init__.py. Run this from your project root (where 'server' folder is located).")

    # Patch assets route
    patched_assets = patch_assets_route(server_init)

    # Patch app.js
    patched_js = patch_app_js(app_js)

    # Ensure logo
    installed_logo = ensure_logo(static_dir)

    if not any([patched_assets, patched_js, installed_logo]):
        info("Nothing to change. Hotfix already applied.")
    else:
        info("Hotfix applied successfully. Restart your server and hard-reload the page.")

if __name__ == "__main__":
    main()
