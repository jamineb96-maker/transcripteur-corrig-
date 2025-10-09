const OVERLAY_ID = 'assist-debug-overlay';

function ensureDiagnosticsShell() {
  if (!document.querySelector('[data-component="diagnostics"]')) {
    const shell = document.createElement('div');
    shell.className = 'diag-panel';
    shell.dataset.component = 'diagnostics';
    shell.id = 'diagnostics-panel';
    shell.setAttribute('aria-hidden', 'true');
    document.body.appendChild(shell);
  }
  if (!document.querySelector('[data-action="toggle-diagnostics"]')) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Diagnostic';
    button.className = 'ghost diag-toggle';
    button.dataset.action = 'toggle-diagnostics';
    button.style.position = 'fixed';
    button.style.bottom = '16px';
    button.style.left = '16px';
    button.style.zIndex = '960';
    button.style.padding = '8px 12px';
    document.body.appendChild(button);
  }
}

function createOverlay() {
  let overlay = document.getElementById(OVERLAY_ID);
  if (overlay) {
    return overlay;
  }
  overlay = document.createElement('div');
  overlay.id = OVERLAY_ID;
  overlay.setAttribute('role', 'status');
  overlay.setAttribute('aria-live', 'polite');
  overlay.style.position = 'fixed';
  overlay.style.top = '16px';
  overlay.style.right = '16px';
  overlay.style.zIndex = '100';
  overlay.style.background = 'rgba(0, 0, 0, 0.8)';
  overlay.style.color = '#fff';
  overlay.style.padding = '10px 14px';
  overlay.style.borderRadius = '8px';
  overlay.style.fontSize = '0.8rem';
  overlay.style.boxShadow = '0 6px 20px rgba(0, 0, 0, 0.35)';
  overlay.style.maxWidth = '320px';
  overlay.style.display = 'none';
  overlay.style.pointerEvents = 'none';
  overlay.innerHTML = '<strong>Diagnostics</strong><div data-debug-detail>Initialisation…</div>';
  document.body.appendChild(overlay);
  return overlay;
}

function hideOverlay() {
  const overlay = createOverlay();
  overlay.style.display = 'none';
  overlay.style.pointerEvents = 'none';
}

function setOverlay(message, tone = 'info') {
  const overlay = createOverlay();
  overlay.style.display = 'block';
  overlay.style.pointerEvents = 'auto';
  overlay.dataset.tone = tone;
  const detail = overlay.querySelector('[data-debug-detail]');
  if (detail) {
    detail.textContent = message;
  }
  overlay.style.background =
    tone === 'error'
      ? 'rgba(192, 57, 43, 0.9)'
      : tone === 'warning'
      ? 'rgba(243, 156, 18, 0.9)'
      : 'rgba(39, 174, 96, 0.9)';
}

async function runSmokeTests() {
  const base = window.__API_BASE__ || '';
  const targets = ['/', '/api/health', '/api/patients'];
  for (const target of targets) {
    const url = target === '/' ? target : `${base}${target}`;
    try {
      // eslint-disable-next-line no-await-in-loop
      const response = await fetch(url, { cache: 'no-store' });
      if (!response.ok) {
        setOverlay(`${target} → ${response.status}`, 'warning');
        return;
      }
    } catch (error) {
      setOverlay(`${target} indisponible (${error instanceof Error ? error.message : error})`, 'error');
      return;
    }
  }
  hideOverlay();
}

function attachGlobalHandlers() {
  window.addEventListener('error', (event) => {
    if (event && event.message) {
      setOverlay(`Erreur JS : ${event.message}`, 'error');
    }
  });
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event && event.reason ? String(event.reason) : 'Promesse rejetée';
    setOverlay(`Rejet non géré : ${reason}`, 'error');
  });
  window.addEventListener('keydown', (event) => {
    if (event.key.toLowerCase() === 'd' && event.ctrlKey && event.shiftKey) {
      const overlay = createOverlay();
      const shouldShow = overlay.style.display === 'none';
      overlay.style.display = shouldShow ? 'block' : 'none';
      overlay.style.pointerEvents = shouldShow ? 'auto' : 'none';
    }
  });
}

function bootstrap() {
  ensureDiagnosticsShell();
  createOverlay();
  attachGlobalHandlers();
  runSmokeTests().catch((error) => {
    setOverlay(`Diagnostic impossible : ${error instanceof Error ? error.message : error}`, 'error');
  });
  window.assistDebug = {
    show(message, tone) {
      setOverlay(message, tone);
    },
    hide() {
      hideOverlay();
    },
    run: runSmokeTests,
  };
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap, { once: true });
} else {
  bootstrap();
}

export {};

