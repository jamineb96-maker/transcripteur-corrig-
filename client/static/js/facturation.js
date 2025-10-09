import { jsonGet, jsonPost } from '../../services/api.js';
import { get as getState } from '../../services/app_state.js';

const ASSET_ENDPOINT = '/billing-assets';

function formatCurrency(value) {
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(value || 0);
}

function buildInvoicePayload(form) {
  const data = new FormData(form);
  const numberMode = data.get('number_mode') || 'auto';
  const payload = {
    date: data.get('date'),
    number_mode: numberMode,
    number: data.get('number') || undefined,
    patient: {
      name: data.get('patient_name') || '',
      address: data.get('patient_address') || '',
    },
    notes: data.get('notes') || '',
    lines: [],
  };
  const rows = form.querySelectorAll('.line');
  rows.forEach((row) => {
    const label = row.querySelector('input[name$="[label]"]');
    const qty = row.querySelector('input[name$="[qty]"]');
    const unit = row.querySelector('input[name$="[unit_price]"]');
    const vat = row.querySelector('input[name$="[vat_rate]"]');
    if (!label) return;
    payload.lines.push({
      label: label.value.trim(),
      qty: parseFloat(qty ? qty.value : '0') || 0,
      unit_price: parseFloat(unit ? unit.value : '0') || 0,
      vat_rate: vat ? parseFloat(vat.value || '0') : 0,
    });
  });
  return payload;
}

function getAppVersions() {
  const metaEl = document.querySelector('meta[data-app-version]');
  return {
    metaVersion: metaEl ? metaEl.dataset.appVersion || metaEl.getAttribute('content') || '' : '',
    runtimeVersion: window.ASSET_VERSION || '',
  };
}

function setDiagnosticsStatus(container, message, isError = false) {
  if (!container) return;
  const statusEl = container.querySelector('[data-role="diagnostics-status"]');
  if (!statusEl) return;
  statusEl.textContent = message || '';
  statusEl.hidden = !message;
  statusEl.classList.toggle('is-error', Boolean(message) && isError);
}

function renderDiagnostics(container, payload) {
  if (!container) return;
  const content = container.querySelector('[data-role="diagnostics-content"]');
  if (!content) return;
  setDiagnosticsStatus(container, '');
  if (!payload || !payload.data) {
    content.innerHTML = '<p>Diagnostic indisponible.</p>';
    return;
  }
  const info = payload.data || {};
  const { metaVersion, runtimeVersion } = getAppVersions();
  const versionMismatch = Boolean(metaVersion && runtimeVersion && metaVersion !== runtimeVersion);
  const logoSvgOk = info.logo_svg_exists ?? info.logo ?? false;
  const signatureOk = info.signature_png_exists ?? info.signature ?? false;
  const rasterOk = info.logo_raster_exists;
  content.innerHTML = `
    <dl>
      <div><dt>Template</dt><dd>${info.template_ready ? '✅' : '⚠️'}</dd></div>
      <div><dt>Logo SVG</dt><dd>${logoSvgOk ? '✅' : '⚠️'}</dd></div>
      <div><dt>Signature</dt><dd>${signatureOk ? '✅' : '⚠️'}</dd></div>
      ${
        rasterOk === undefined
          ? ''
          : `<div><dt>Logo raster</dt><dd>${rasterOk ? '✅' : '⚠️'}</dd></div>`
      }
      <div><dt>LibreOffice</dt><dd>${info.soffice_found ? '✅' : '⚠️'}</dd></div>
      <div><dt>Fallback</dt><dd>${info.fallback_ready ? '✅' : '⚠️'}</dd></div>
      <div><dt>Version HTML</dt><dd>${metaVersion || '—'}</dd></div>
      <div><dt>Version scripts</dt><dd>${runtimeVersion || '—'}${versionMismatch ? ' ⚠️' : ''}</dd></div>
    </dl>
    ${
      versionMismatch
        ? '<p class="facturation__diagnostics-note">Versions différentes détectées. Purgez le cache puis rechargez.</p>'
        : ''
    }
  `;
}

function updateAssetPreviews(root) {
  const ts = Date.now();
  const logo = root.querySelector('[data-role="logo-preview"]');
  const signature = root.querySelector('[data-role="signature-preview"]');
  if (logo) {
    logo.src = `${ASSET_ENDPOINT}/logo.svg?v=${ts}`;
  }
  if (signature) {
    signature.src = `${ASSET_ENDPOINT}/signature.png?v=${ts}`;
  }
}

async function replaceAsset(kind, root, alertEl) {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = kind === 'logo' ? 'image/svg+xml' : 'image/png,image/*';
    input.addEventListener('change', async () => {
      const file = input.files && input.files[0];
      if (!file) {
        resolve(false);
        return;
      }
      try {
        const form = new FormData();
        form.append('file', file, file.name);
        const response = await fetch(`/api/assets/upload?kind=${kind}`, {
          method: 'POST',
          body: form,
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data && data.message ? data.message : 'Échec du téléversement.');
        }
        updateAssetPreviews(root);
        setAlert(alertEl, `${kind === 'logo' ? 'Logo' : 'Signature'} mis à jour avec succès.`, false);
        resolve(true);
      } catch (error) {
        setAlert(alertEl, error.message || 'Impossible de mettre à jour l’actif.', true);
        resolve(false);
      }
    });
    input.click();
  });
}

function setAlert(alertEl, message, isError = false) {
  if (!alertEl) return;
  alertEl.hidden = !message;
  alertEl.textContent = message || '';
  alertEl.classList.toggle('is-error', Boolean(message) && isError);
}

function toggleManualNumberField(form) {
  const manualField = form.querySelector('[data-role="manual-number"]');
  const mode = form.querySelector('input[name="number_mode"]:checked');
  if (!manualField || !mode) return;
  const manual = mode.value === 'manual';
  manualField.hidden = !manual;
  manualField.required = manual;
  if (!manual) {
    manualField.value = '';
  }
}

function createLineNode(index) {
  const div = document.createElement('div');
  div.className = 'line';
  div.dataset.index = String(index);
  div.innerHTML = `
    <input type="text" name="lines[${index}][label]" required />
    <input type="number" name="lines[${index}][qty]" min="0" step="0.5" value="1" required />
    <input type="number" name="lines[${index}][unit_price]" min="0" step="0.1" value="0" required />
    <input type="hidden" name="lines[${index}][vat_rate]" value="0" />
    <button type="button" class="ghost" data-action="remove-line" aria-label="Supprimer la ligne">✕</button>
  `;
  return div;
}

function serialiseFilters(form) {
  const params = new URLSearchParams();
  const data = new FormData(form);
  for (const [key, value] of data.entries()) {
    if (value) params.append(key, value);
  }
  return params.toString() ? `?${params.toString()}` : '';
}

function renderInvoices(container, invoices) {
  if (!container) return;
  if (!invoices || !invoices.length) {
    container.innerHTML = '<p>Aucune facture enregistrée.</p>';
    return;
  }
  container.innerHTML = '';
  invoices.forEach((invoice) => {
    const card = document.createElement('article');
    card.className = 'invoice-card';
    card.innerHTML = `
      <div class="invoice-card__info">
        <strong>${invoice.number}</strong>
        <span>${invoice.patient_name} — ${invoice.date}</span>
        <span>${formatCurrency(invoice.total_ttc)}</span>
      </div>
      <div class="invoice-card__actions">
        <span class="invoice-card__status">${invoice.paid ? 'Payée' : 'À régler'}</span>
        <a class="ghost" href="${invoice.file_url}" target="_blank" rel="noreferrer">PDF</a>
        ${invoice.paid ? '' : '<button type="button" data-action="mark-paid">Marquer payé</button>'}
      </div>
    `;
    card.dataset.id = invoice.id;
    container.appendChild(card);
  });
}

async function markInvoicePaid(id, card) {
  const amountEl = card.querySelector('.invoice-card__info span:nth-child(3)');
  const amountText = amountEl ? amountEl.textContent || '' : '';
  const match = amountText.match(/([0-9]+(?:[\s\u00a0][0-9]{3})*,[0-9]{2})/);
  const amount = match ? parseFloat(match[1].replace(/\s|\u00a0/g, '').replace(',', '.')) : undefined;
  const value = window.prompt('Montant encaissé (€)', amount != null ? amount : '0');
  if (value === null) return false;
  const numberValue = parseFloat(value.replace(',', '.'));
  if (!Number.isFinite(numberValue) || numberValue <= 0) {
    alert('Montant invalide.');
    return false;
  }
  const payload = {
    amount: numberValue,
    method: 'Encaissement',
    date: new Date().toISOString().slice(0, 10),
  };
  const result = await jsonPost(`/api/invoices/${id}/pay`, payload);
  return result;
}

export function createFacturationController(root) {
  const elements = {
    diagnostics: root.querySelector('[data-role="diagnostics"]'),
    form: root.querySelector('[data-role="invoice-form"]'),
    manualNumber: root.querySelector('[data-role="manual-number"]'),
    addLine: root.querySelector('[data-action="add-line"]'),
    lineContainer: root.querySelector('[data-role="line-items"]'),
    formAlert: root.querySelector('[data-role="form-alert"]'),
    previewImage: root.querySelector('[data-role="preview-image"]'),
    previewButton: root.querySelector('[data-action="preview"]'),
    filters: root.querySelector('[data-role="filters"]'),
    invoiceList: root.querySelector('[data-role="invoice-list"]'),
    replaceLogo: root.querySelector('[data-action="replace-logo"]'),
    replaceSignature: root.querySelector('[data-action="replace-signature"]'),
  };

  async function loadDiagnostics() {
    try {
      const data = await jsonGet('/api/invoices/diagnostics');
      renderDiagnostics(elements.diagnostics, data);
    } catch (error) {
      renderDiagnostics(elements.diagnostics, null);
    }
  }

  async function purgeCaches(containerEl) {
    if (!containerEl) return;
    setDiagnosticsStatus(containerEl, 'Purge du cache en cours…');
    let swCount = 0;
    let cacheCount = 0;
    try {
      if ('serviceWorker' in navigator) {
        await navigator.serviceWorker.getRegistrations().then((registrations) => {
          swCount = registrations.length;
          registrations.forEach((registration) => registration.unregister());
        });
      }
      if ('caches' in window) {
        await caches.keys().then((keys) => {
          cacheCount = keys.length;
          return Promise.all(keys.map((key) => caches.delete(key)));
        });
      }
      const details = [];
      if ('serviceWorker' in navigator) {
        details.push(`${swCount} SW désinscrit${swCount > 1 ? 's' : ''}`);
      }
      if ('caches' in window) {
        details.push(`${cacheCount} cache${cacheCount > 1 ? 's' : ''} supprimé${cacheCount > 1 ? 's' : ''}`);
      }
      const message = details.length
        ? `Cache purgé (${details.join(', ')}). Rechargez l’application.`
        : 'Cache purgé. Rechargez l’application.';
      setDiagnosticsStatus(containerEl, message);
    } catch (error) {
      console.error('Erreur lors de la purge du cache', error);
      setDiagnosticsStatus(containerEl, 'Échec de la purge du cache.', true);
    }
  }

  async function loadInvoices() {
    if (!elements.invoiceList) return;
    const query = elements.filters ? serialiseFilters(elements.filters) : '';
    try {
      const data = await jsonGet(`/api/invoices${query}`);
      renderInvoices(elements.invoiceList, Array.isArray(data?.invoices) ? data.invoices : []);
    } catch (error) {
      elements.invoiceList.innerHTML = `<p>Impossible de charger les factures : ${error.message}</p>`;
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    buildInvoicePayload(elements.form);
    setAlert(elements.formAlert, '', false);
    setAlert(
      elements.formAlert,
      'La génération de facture complète n’est pas encore disponible dans cette version démo.',
      true,
    );
  }

  async function handlePreview(event) {
    event.preventDefault();
    if (!elements.form) return;
    buildInvoicePayload(elements.form);
    setAlert(elements.formAlert, '', false);
    setAlert(
      elements.formAlert,
      "L’aperçu PDF sera disponible dès que le moteur de facturation sera branché.",
      true,
    );
  }

  function bindEvents() {
    if (elements.form) {
      elements.form.addEventListener('submit', handleSubmit);
      elements.form.addEventListener('change', (event) => {
        if (event.target && event.target.name === 'number_mode') {
          toggleManualNumberField(elements.form);
        }
      });
    }
    if (elements.previewButton) {
      elements.previewButton.addEventListener('click', handlePreview);
    }
    if (elements.addLine && elements.lineContainer) {
      elements.addLine.addEventListener('click', () => {
        const current = elements.lineContainer.querySelectorAll('.line').length;
        const node = createLineNode(current);
        elements.lineContainer.appendChild(node);
      });
      elements.lineContainer.addEventListener('click', (event) => {
        const target = event.target;
        if (target && target.matches('[data-action="remove-line"]')) {
          const line = target.closest('.line');
          if (line && elements.lineContainer.querySelectorAll('.line').length > 1) {
            line.remove();
          }
        }
      });
    }
    if (elements.filters) {
      elements.filters.addEventListener('change', loadInvoices);
      elements.filters.addEventListener('input', (event) => {
        if (event.target && event.target.name === 'patient') {
          loadInvoices();
        }
      });
    }
    if (elements.invoiceList) {
      elements.invoiceList.addEventListener('click', async (event) => {
        const target = event.target;
        if (target && target.matches('button[data-action="mark-paid"]')) {
          const card = target.closest('.invoice-card');
          if (!card) return;
          const id = card.dataset.id;
          try {
            await markInvoicePaid(id, card);
            loadInvoices();
          } catch (error) {
            alert(error.message || 'Impossible de marquer la facture comme payée.');
          }
        }
      });
    }
    if (elements.diagnostics) {
      elements.diagnostics.addEventListener('click', (event) => {
        const target = event.target;
        if (target && target.matches('button[data-action="purge-cache"]')) {
          purgeCaches(elements.diagnostics);
        }
      });
    }
    if (elements.replaceLogo) {
      elements.replaceLogo.addEventListener('click', () => replaceAsset('logo', root, elements.formAlert));
    }
    if (elements.replaceSignature) {
      elements.replaceSignature.addEventListener('click', () => replaceAsset('signature', root, elements.formAlert));
    }
  }

  function init() {
    updateAssetPreviews(root);
    toggleManualNumberField(elements.form);
    const patientId = getState('selectedPatientId');
    const patients = getState('patientsCache') || [];
    if (patientId && elements.form) {
      const patient = patients.find((p) => p.id === patientId);
      if (patient) {
        const nameInput = elements.form.querySelector('#patient-name');
        if (nameInput) nameInput.value = patient.displayName || '';
      }
    }
    bindEvents();
    loadDiagnostics();
    loadInvoices();
  }

  function destroy() {
    // Listeners are attached to static nodes; letting GC collect is enough when section is removed.
  }

  function setPatientName(name) {
    if (!elements.form) return;
    const input = elements.form.querySelector('#patient-name');
    if (input) input.value = name || '';
  }

  return { init, destroy, setPatientName, refresh: loadInvoices };
}
