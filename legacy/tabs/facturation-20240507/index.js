import { API_BASE, jsonGet, jsonPost } from '../../../services/api.js';
import { get as getState } from '../../../services/app_state.js';

const EUR_FORMATTER = new Intl.NumberFormat('fr-FR', {
  style: 'currency',
  currency: 'EUR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function computeServiceTitle(amount) {
  const value = Number.parseFloat(amount);
  if (!Number.isFinite(value)) {
    return 'Consultation psy';
  }
  return value < 60 ? 'Consultation tarif solidaire' : 'Consultation psy';
}

function formatCurrency(value) {
  return EUR_FORMATTER.format(Number.isFinite(value) ? value : 0);
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) {
      const [year, month, day] = iso.split('-');
      if (year && month && day) {
        return `${day}/${month}/${year}`;
      }
      return iso;
    }
    return date.toLocaleDateString('fr-FR');
  } catch (error) {
    return iso;
  }
}

async function jsonDelete(url) {
  const resp = await fetch(`${API_BASE}${url}`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  });
  const contentType = resp.headers.get('Content-Type') || '';
  const payload = contentType.includes('application/json') ? await resp.json() : await resp.text();
  if (!resp.ok) {
    const message = (payload && payload.error) || resp.statusText || 'Suppression impossible';
    const err = new Error(message);
    err.data = payload;
    err.status = resp.status;
    throw err;
  }
  return payload;
}

function toCSVRow(values) {
  return values
    .map((value) => {
      if (value == null) return '';
      const stringValue = String(value).replace(/"/g, '""');
      return `"${stringValue}"`;
    })
    .join(';');
}

function buildCSV(invoices) {
  const header = toCSVRow([
    'Numéro',
    'Date',
    'Patient',
    'Patient ID',
    'Montant',
    'Envoyée',
    'Payée',
    'Mode de règlement',
  ]);
  const rows = invoices.map((invoice) =>
    toCSVRow([
      invoice.number,
      invoice.date,
      invoice.patient,
      invoice.patient_id,
      invoice.amount,
      invoice.sent ? 'oui' : 'non',
      invoice.paid ? 'oui' : 'non',
      invoice.paid_via || '',
    ]),
  );
  return [header, ...rows].join('\n');
}

function ensureBlobDownload(content, filename, type = 'text/csv') {
  const blob = new Blob([content], { type });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(link.href);
    link.remove();
  }, 100);
}

export function createFacturationController(root) {
  const elements = {
    patientSelect: root.querySelector('[data-role="patient-select"]'),
    filters: root.querySelector('[data-role="filters"]'),
    filtersMeta: root.querySelector('[data-role="filters-meta"]'),
    yearFilter: root.querySelector('[data-role="year-filter"]'),
    tableBody: root.querySelector('[data-role="invoices-body"]'),
    newInvoice: root.querySelector('[data-action="new-invoice"]'),
    refresh: root.querySelector('[data-action="refresh"]'),
    exportCsv: root.querySelector('[data-action="export-csv"]'),
    drawer: root.querySelector('[data-role="drawer"]'),
    backdrop: root.querySelector('[data-role="backdrop"]'),
    form: root.querySelector('[data-role="invoice-form"]'),
    patientField: root.querySelector('[data-role="patient-id"]'),
    patientNameField: root.querySelector('input[name="patient_name"]'),
    dateField: root.querySelector('input[name="date"]'),
    numberField: root.querySelector('input[name="number"]'),
    amountTabs: root.querySelector('[data-role="amount-tabs"]'),
    simpleAmount: root.querySelector('[data-role="simple-amount"]'),
    linesPanel: root.querySelector('[data-role="lines"]'),
    linesBody: root.querySelector('[data-role="lines-body"]'),
    addLineButton: root.querySelector('[data-action="add-line"]'),
    formAlert: root.querySelector('[data-role="form-alert"]'),
    previewSection: root.querySelector('[data-role="preview"]'),
    previewObject: root.querySelector('[data-role="preview-object"]'),
    previewActions: root.querySelector('[data-role="preview-actions"]'),
    previewPdf: root.querySelector('[data-role="download-pdf"]'),
    previewSvg: root.querySelector('[data-role="download-svg"]'),
    closeDrawer: root.querySelector('[data-action="close-drawer"]'),
    previewButton: root.querySelector('[data-action="preview"]'),
  };

  let invoices = [];
  let selectedPatient = null;
  let debounceTimer = null;
  let destroyers = [];
  let lastPreviewPaths = null;

  function on(target, event, handler) {
    if (!target) return;
    target.addEventListener(event, handler);
    destroyers.push(() => target.removeEventListener(event, handler));
  }

  function setAlert(message, isError = false) {
    if (!elements.formAlert) return;
    if (message) {
      elements.formAlert.textContent = message;
      elements.formAlert.hidden = false;
      elements.formAlert.classList.toggle('is-error', isError);
    } else {
      elements.formAlert.textContent = '';
      elements.formAlert.hidden = true;
      elements.formAlert.classList.remove('is-error');
    }
  }

  function updateFiltersMeta(count) {
    if (!elements.filtersMeta) return;
    const total = count != null ? count : invoices.length;
    elements.filtersMeta.textContent = total ? `${total} facture${total > 1 ? 's' : ''}` : 'Aucune facture';
  }

  function computeYears(list) {
    const years = new Set();
    list.forEach((invoice) => {
      const yearFromNumber = invoice.number && String(invoice.number).split('-')[0];
      if (yearFromNumber && yearFromNumber.length === 4) {
        years.add(yearFromNumber);
      } else if (invoice.date) {
        const candidate = String(invoice.date).slice(0, 4);
        if (candidate) years.add(candidate);
      }
    });
    return Array.from(years).sort((a, b) => Number(b) - Number(a));
  }

  function renderYearOptions(list) {
    if (!elements.yearFilter) return;
    const current = elements.yearFilter.value;
    const years = computeYears(list);
    elements.yearFilter.innerHTML = '<option value="">Toutes</option>';
    years.forEach((year) => {
      const option = document.createElement('option');
      option.value = year;
      option.textContent = year;
      elements.yearFilter.appendChild(option);
    });
    if (current && years.includes(current)) {
      elements.yearFilter.value = current;
    }
  }

  function filterInvoices(list) {
    if (!elements.filters) return list;
    const formData = new FormData(elements.filters);
    const status = formData.get('status') || 'all';
    const q = (formData.get('q') || '').toString().trim().toLowerCase();
    const year = (formData.get('year') || '').toString().trim();
    return list.filter((invoice) => {
      if (year) {
        const byNumber = invoice.number && String(invoice.number).startsWith(`${year}-`);
        const byDate = invoice.date && String(invoice.date).startsWith(year);
        if (!byNumber && !byDate) return false;
      }
      if (q) {
        const haystack = `${invoice.number || ''} ${invoice.patient || ''} ${invoice.patient_id || ''}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      if (status === 'sent' && !invoice.sent) return false;
      if (status === 'not-sent' && invoice.sent) return false;
      if (status === 'paid' && !invoice.paid) return false;
      if (status === 'not-paid' && invoice.paid) return false;
      return true;
    });
  }

  function createStatusBadge(label, variant) {
    const span = document.createElement('span');
    span.className = 'facturation__badge';
    if (variant === 'positive') span.classList.add('facturation__badge--positive');
    if (variant === 'warning') span.classList.add('facturation__badge--warning');
    span.textContent = label;
    return span;
  }

  function renderInvoices(list) {
    if (!elements.tableBody) return;
    elements.tableBody.innerHTML = '';
    if (!list.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 7;
      cell.className = 'facturation__empty';
      cell.textContent = 'Aucune facture à afficher.';
      row.appendChild(cell);
      elements.tableBody.appendChild(row);
      updateFiltersMeta(0);
      return;
    }

    list.forEach((invoice) => {
      const row = document.createElement('tr');
      row.dataset.number = invoice.number || '';

      const dateCell = document.createElement('td');
      dateCell.textContent = formatDate(invoice.date);
      row.appendChild(dateCell);

      const numberCell = document.createElement('td');
      numberCell.textContent = invoice.number || '—';
      row.appendChild(numberCell);

      const patientCell = document.createElement('td');
      patientCell.textContent = invoice.patient || '—';
      row.appendChild(patientCell);

      const amountCell = document.createElement('td');
      amountCell.textContent = formatCurrency(invoice.amount || 0);
      row.appendChild(amountCell);

      const statusCell = document.createElement('td');
      statusCell.className = 'facturation__statuses';
      statusCell.appendChild(
        createStatusBadge(invoice.sent ? 'Envoyée' : 'Non envoyée', invoice.sent ? 'positive' : 'warning'),
      );
      statusCell.appendChild(
        createStatusBadge(invoice.paid ? 'Payée' : 'Non payée', invoice.paid ? 'positive' : 'warning'),
      );
      row.appendChild(statusCell);

      const filesCell = document.createElement('td');
      filesCell.className = 'facturation__row-actions';
      const svgPath = invoice.paths && invoice.paths.svg ? invoice.paths.svg : null;
      const pdfPath = invoice.paths && invoice.paths.pdf ? invoice.paths.pdf : null;
      if (pdfPath) {
        const link = document.createElement('a');
        link.href = pdfPath;
        link.target = '_blank';
        link.rel = 'noreferrer';
        link.textContent = 'PDF';
        filesCell.appendChild(link);
      }
      if (svgPath) {
        const link = document.createElement('a');
        link.href = svgPath;
        link.target = '_blank';
        link.rel = 'noreferrer';
        link.textContent = 'SVG';
        filesCell.appendChild(link);
      }
      row.appendChild(filesCell);

      const actionsCell = document.createElement('td');
      actionsCell.className = 'facturation__row-actions';

      const sentToggle = document.createElement('label');
      sentToggle.className = 'facturation__toggle';
      sentToggle.innerHTML = `
        <input type="checkbox" data-action="toggle-sent" ${invoice.sent ? 'checked' : ''} />
        <span>Envoyée</span>
      `;
      actionsCell.appendChild(sentToggle);

      const paidToggle = document.createElement('label');
      paidToggle.className = 'facturation__toggle';
      paidToggle.innerHTML = `
        <input type="checkbox" data-action="toggle-paid" ${invoice.paid ? 'checked' : ''} />
        <span>Payée</span>
      `;
      actionsCell.appendChild(paidToggle);

      const renameButton = document.createElement('button');
      renameButton.type = 'button';
      renameButton.dataset.action = 'rename';
      renameButton.className = 'ghost';
      renameButton.textContent = 'Renommer';
      actionsCell.appendChild(renameButton);

      const deleteButton = document.createElement('button');
      deleteButton.type = 'button';
      deleteButton.dataset.action = 'delete';
      deleteButton.className = 'ghost';
      deleteButton.textContent = 'Supprimer';
      actionsCell.appendChild(deleteButton);

      row.appendChild(actionsCell);
      elements.tableBody.appendChild(row);
    });

    updateFiltersMeta(list.length);
  }

  async function fetchInvoices() {
    if (!elements.filters) return;
    const params = new URLSearchParams();
    if (selectedPatient && selectedPatient.slug) {
      params.set('patient', selectedPatient.slug);
    }
    const formData = new FormData(elements.filters);
    const q = (formData.get('q') || '').toString().trim();
    const year = (formData.get('year') || '').toString().trim();
    if (q) params.set('q', q);
    if (year) params.set('year', year);

    try {
      const response = await jsonGet(`/api/invoices${params.toString() ? `?${params.toString()}` : ''}`);
      invoices = Array.isArray(response?.invoices) ? response.invoices : [];
      renderYearOptions(invoices);
      renderInvoices(filterInvoices(invoices));
    } catch (error) {
      setAlert(error.message || 'Impossible de charger les factures.', true);
    }
  }

  function openDrawer() {
    if (!elements.drawer) return;
    elements.drawer.classList.add('is-open');
    elements.drawer.setAttribute('aria-hidden', 'false');
    if (elements.backdrop) {
      elements.backdrop.classList.remove('hidden');
    }
    if (elements.form) {
      elements.form.reset();
      if (elements.dateField) {
        const today = new Date().toISOString().slice(0, 10);
        elements.dateField.value = today;
      }
      if (elements.patientNameField) {
        elements.patientNameField.value = selectedPatient ? selectedPatient.displayName || '' : '';
      }
      if (elements.patientField) {
        elements.patientField.value = selectedPatient ? selectedPatient.slug || selectedPatient.id || '' : '';
      }
      if (elements.amountTabs) {
        switchAmountMode('amount');
      }
    }
    lastPreviewPaths = null;
    setAlert('');
    resetPreview();
    ensureLineCount(1);
  }

  function closeDrawer() {
    if (!elements.drawer) return;
    elements.drawer.classList.remove('is-open');
    elements.drawer.setAttribute('aria-hidden', 'true');
    if (elements.backdrop) {
      elements.backdrop.classList.add('hidden');
    }
  }

  function resetPreview() {
    if (elements.previewSection) {
      elements.previewSection.hidden = true;
    }
    if (elements.previewActions) {
      elements.previewActions.hidden = true;
    }
    if (elements.previewObject) {
      elements.previewObject.data = '';
    }
  }

  function switchAmountMode(mode) {
    if (!elements.amountTabs) return;
    const buttons = Array.from(elements.amountTabs.querySelectorAll('button[data-mode]'));
    buttons.forEach((button) => {
      button.classList.toggle('is-active', button.dataset.mode === mode);
    });
    if (elements.simpleAmount) {
      elements.simpleAmount.hidden = mode !== 'amount';
    }
    if (elements.linesPanel) {
      elements.linesPanel.hidden = mode !== 'lines';
    }
    if (mode === 'lines') {
      ensureLineCount(elements.linesBody && elements.linesBody.children.length ? elements.linesBody.children.length : 1);
      updateLineDescriptions();
      updateLineTotals();
    }
  }

  function ensureLineCount(count) {
    if (!elements.linesBody) return;
    while (elements.linesBody.children.length < count) {
      addLine();
    }
    while (elements.linesBody.children.length > count) {
      elements.linesBody.removeChild(elements.linesBody.lastChild);
    }
    updateLineDescriptions();
    updateLineTotals();
  }

  function addLine(data = {}) {
    if (!elements.linesBody) return;
    const row = document.createElement('tr');
    const unitPrice = data.pu != null ? data.pu : 60;
    const serviceTitle = computeServiceTitle(unitPrice);
    row.innerHTML = `
      <td><input type="date" name="line-date" value="${data.date || (elements.dateField ? elements.dateField.value : '')}" /></td>
      <td><input type="text" name="line-desc" value="${serviceTitle}" readonly aria-readonly="true" /></td>
      <td><input type="text" name="line-duration" value="${data.duree || data.duration || '50 min'}" /></td>
      <td><input type="number" step="0.01" min="0" name="line-unit" value="${unitPrice}" /></td>
      <td><input type="number" step="0.1" min="0" name="line-qty" value="${data.qty != null ? data.qty : 1}" /></td>
      <td data-role="line-total">${formatCurrency((data.pu || 60) * (data.qty || 1))}</td>
      <td><button type="button" class="ghost" data-action="remove-line" aria-label="Supprimer">✕</button></td>
    `;
    elements.linesBody.appendChild(row);
    updateLineDescriptions();
    updateLineTotals();
  }

  function updateLineTotals() {
    if (!elements.linesBody) return;
    elements.linesBody.querySelectorAll('tr').forEach((row) => {
      const unit = parseFloat(row.querySelector('input[name="line-unit"]').value || '0');
      const qty = parseFloat(row.querySelector('input[name="line-qty"]').value || '0');
      const cell = row.querySelector('[data-role="line-total"]');
      if (cell) {
        cell.textContent = formatCurrency((Number.isFinite(unit) ? unit : 0) * (Number.isFinite(qty) ? qty : 0));
      }
    });
  }

  function updateLineDescriptions() {
    if (!elements.linesBody) return;
    elements.linesBody.querySelectorAll('tr').forEach((row) => {
      const unitInput = row.querySelector('input[name="line-unit"]');
      const descInput = row.querySelector('input[name="line-desc"]');
      if (!unitInput || !descInput) return;
      const nextTitle = computeServiceTitle(unitInput.value || '');
      if (descInput.value !== nextTitle) {
        descInput.value = nextTitle;
      }
    });
  }

  function gatherFormPayload() {
    if (!elements.form) return null;
    const formData = new FormData(elements.form);
    const modeButton = elements.amountTabs?.querySelector('button.is-active');
    const mode = modeButton ? modeButton.dataset.mode : 'amount';
    const patientId = formData.get('patient_id') || (selectedPatient ? selectedPatient.slug || selectedPatient.id : '');
    const patientName = formData.get('patient_name') || '';
    const payload = {
      patient_id: patientId ? String(patientId).trim() : '',
      patient_name: patientName ? String(patientName).trim() : '',
      address: String(formData.get('address') || ''),
      paid_via: String(formData.get('paid_via') || ''),
      date: formData.get('date') || new Date().toISOString().slice(0, 10),
      number: String(formData.get('number') || '').trim() || undefined,
      replace: true,
    };

    if (mode === 'lines' && elements.linesBody) {
      const lines = [];
      elements.linesBody.querySelectorAll('tr').forEach((row) => {
        const date = row.querySelector('input[name="line-date"]').value || payload.date;
        const duration = row.querySelector('input[name="line-duration"]').value || '50 min';
        const unit = parseFloat(row.querySelector('input[name="line-unit"]').value || '0');
        const qty = parseFloat(row.querySelector('input[name="line-qty"]').value || '0');
        const safeUnit = Number.isFinite(unit) && unit >= 0 ? unit : 0;
        const safeQty = Number.isFinite(qty) && qty >= 0 ? qty : 0;
        const desc = computeServiceTitle(safeUnit);
        if (!desc.trim()) return;
        lines.push({
          date,
          desc,
          duree: duration,
          duration,
          pu: safeUnit,
          qty: safeQty,
        });
      });
      if (!lines.length) {
        setAlert('Ajoutez au moins une ligne pour générer la facture.', true);
        return null;
      }
      payload.lines = lines;
    } else {
      const amountValue = parseFloat(formData.get('amount') || '0');
      payload.amount = Number.isFinite(amountValue) && amountValue >= 0 ? amountValue : 0;
    }

    if (!payload.patient_id) {
      setAlert('Sélectionnez un patient valide avant de générer la facture.', true);
      return null;
    }
    if (!payload.patient_name) {
      setAlert('Le nom du destinataire est requis.', true);
      return null;
    }
    return payload;
  }

  function showPreview(paths) {
    if (!paths) return;
    lastPreviewPaths = paths;
    if (elements.previewPdf) {
      elements.previewPdf.href = paths.pdf;
    }
    if (elements.previewSvg) {
      elements.previewSvg.href = paths.svg;
    }
    if (elements.previewActions) {
      elements.previewActions.hidden = !(paths.pdf || paths.svg);
    }
    if (elements.previewSection) {
      elements.previewSection.hidden = false;
    }
    if (elements.previewObject && paths.svg) {
      const ts = Date.now();
      elements.previewObject.data = `${paths.svg}?v=${ts}`;
    }
  }

  async function submitForm(event) {
    event.preventDefault();
    const payload = gatherFormPayload();
    if (!payload) return;
    setAlert('Génération en cours…');
    try {
      const response = await jsonPost('/api/invoices', payload);
      setAlert('Facture générée avec succès.', false);
      if (response?.invoice?.paths) {
        showPreview(response.invoice.paths);
      }
      await fetchInvoices();
    } catch (error) {
      setAlert(error.message || 'Impossible de générer la facture.', true);
    }
  }

  function handlePreview() {
    if (lastPreviewPaths) {
      showPreview(lastPreviewPaths);
      setAlert('Aperçu mis à jour.', false);
    } else {
      setAlert('Générez une facture pour afficher l’aperçu.', true);
    }
  }

  async function handleRowAction(event) {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const row = target.closest('tr');
    if (!row) return;
    const number = row.dataset.number;
    if (!number) return;
    const invoice = invoices.find((item) => item.number === number);

    if (target.matches('[data-action="toggle-sent"]')) {
      try {
        await jsonPost('/api/invoices/mark', { number, sent: target.checked });
        await fetchInvoices();
      } catch (error) {
        setAlert(error.message || 'Impossible de mettre à jour le statut envoyé.', true);
      }
    } else if (target.matches('[data-action="toggle-paid"]')) {
      try {
        await jsonPost('/api/invoices/mark', { number, paid: target.checked });
        await fetchInvoices();
      } catch (error) {
        setAlert(error.message || 'Impossible de mettre à jour le statut payé.', true);
      }
    } else if (target.matches('[data-action="rename"]')) {
      const nextNumber = window.prompt('Nouveau numéro', number);
      if (!nextNumber || nextNumber === number) return;
      if (!invoice) return;
      const payload = {
        patient_id: invoice.patient_id,
        patient_name: invoice.patient,
        address: invoice.address || '',
        paid_via: invoice.paid_via || '',
        date: invoice.date,
        number: nextNumber.trim(),
        replace: true,
      };
      if (Array.isArray(invoice.lines) && invoice.lines.length) {
        payload.lines = invoice.lines;
      } else {
        payload.amount = invoice.amount || 0;
      }
      try {
        await jsonPost('/api/invoices', payload);
        await jsonDelete(`/api/invoices/${encodeURIComponent(number)}`);
        await fetchInvoices();
      } catch (error) {
        setAlert(error.message || 'Impossible de renommer la facture.', true);
      }
    } else if (target.matches('[data-action="delete"]')) {
      if (!window.confirm('Supprimer cette facture ? Cette action est définitive.')) return;
      try {
        await jsonDelete(`/api/invoices/${encodeURIComponent(number)}`);
        await fetchInvoices();
      } catch (error) {
        setAlert(error.message || 'Impossible de supprimer la facture.', true);
      }
    }
  }

  function exportCsv() {
    const filtered = filterInvoices(invoices);
    if (!filtered.length) {
      setAlert('Aucune facture à exporter.', true);
      return;
    }
    const csv = buildCSV(filtered);
    ensureBlobDownload(csv, 'factures.csv');
  }

  function applyPatientSelection(patient) {
    selectedPatient = patient;
    if (elements.patientSelect) {
      const value = patient ? patient.id || patient.slug : '';
      elements.patientSelect.value = value || '';
    }
    if (elements.patientField) {
      elements.patientField.value = patient ? patient.slug || patient.id || '' : '';
    }
    if (elements.patientNameField) {
      elements.patientNameField.value = patient ? patient.displayName || '' : '';
    }
  }

  function populatePatients() {
    if (!elements.patientSelect) return;
    const patients = getState('patientsCache') || [];
    elements.patientSelect.innerHTML = '<option value="">Sans patient</option>';
    patients.forEach((patient) => {
      const option = document.createElement('option');
      option.value = patient.id;
      option.textContent = patient.displayName;
      option.dataset.slug = patient.slug;
      elements.patientSelect.appendChild(option);
    });
  }

  function scheduleRefresh() {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    debounceTimer = window.setTimeout(() => {
      fetchInvoices();
    }, 250);
  }

  function bindEvents() {
    on(elements.newInvoice, 'click', openDrawer);
    on(elements.closeDrawer, 'click', closeDrawer);
    on(elements.backdrop, 'click', closeDrawer);
    on(elements.refresh, 'click', () => fetchInvoices());
    on(elements.exportCsv, 'click', exportCsv);
    if (elements.filters) {
      on(elements.filters, 'input', scheduleRefresh);
      on(elements.filters, 'change', scheduleRefresh);
    }
    on(elements.amountTabs, 'click', (event) => {
      const button = event.target.closest('button[data-mode]');
      if (!button) return;
      switchAmountMode(button.dataset.mode);
    });
    on(elements.addLineButton, 'click', () => addLine());
    if (elements.linesBody) {
      on(elements.linesBody, 'input', (event) => {
        const target = event.target;
        if (target && target.matches('input[name="line-unit"], input[name="line-qty"]')) {
          updateLineTotals();
          updateLineDescriptions();
        }
      });
      on(elements.linesBody, 'click', (event) => {
        const target = event.target;
        if (target && target.matches('[data-action="remove-line"]')) {
          const row = target.closest('tr');
          if (row) {
            row.remove();
            if (!elements.linesBody.children.length) {
              addLine();
            }
          }
        }
      });
    }
    on(elements.form, 'submit', submitForm);
    on(elements.previewButton, 'click', (event) => {
      event.preventDefault();
      handlePreview();
    });
    if (elements.patientSelect) {
      on(elements.patientSelect, 'change', (event) => {
        const patients = getState('patientsCache') || [];
        const next = patients.find((item) => item.id === event.target.value) || null;
        applyPatientSelection(next);
        fetchInvoices();
      });
    }
    if (elements.tableBody) {
      on(elements.tableBody, 'click', handleRowAction);
      on(elements.tableBody, 'change', handleRowAction);
    }
  }

  function init() {
    populatePatients();
    bindEvents();
    if (elements.dateField && !elements.dateField.value) {
      elements.dateField.value = new Date().toISOString().slice(0, 10);
    }
    switchAmountMode('amount');
    ensureLineCount(1);
    fetchInvoices();
  }

  function destroy() {
    destroyers.forEach((fn) => fn());
    destroyers = [];
    invoices = [];
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
  }

  function refresh() {
    fetchInvoices();
  }

  function setPatient(patient) {
    populatePatients();
    applyPatientSelection(patient);
  }

  return {
    init,
    destroy,
    refresh,
    setPatient,
  };
}
