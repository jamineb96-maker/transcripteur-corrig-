import { createPatient, slugify } from '../services/patients.js';

let modalHost;
let modalEl;
let formEl;
let nameInput;
let slugInput;
let emailInput;
let errorEl;
let submitBtn;
let active = false;
let slugDirty = false;
let openerButton;

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input:not([disabled]), select:not([disabled]), [tabindex="0"]';

function ensureModal() {
  if (modalEl) {
    return;
  }
  modalHost = document.querySelector('[data-modal-root]') || document.body;
  modalEl = document.createElement('div');
  modalEl.className = 'modal-backdrop hidden';
  modalEl.setAttribute('aria-hidden', 'true');
  modalEl.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="new-patient-title">
      <header class="modal-header">
        <h2 id="new-patient-title">Nouveau patient</h2>
        <button type="button" class="ghost" data-modal-close aria-label="Fermer">✕</button>
      </header>
      <form data-new-patient-form autocomplete="off">
        <div class="modal-body">
          <label for="patient-name-input">Nom complet <span aria-hidden="true">*</span></label>
          <input id="patient-name-input" name="displayName" type="text" required autocomplete="off" />
          <label for="patient-slug-input">Identifiant</label>
          <input id="patient-slug-input" name="slug" type="text" required autocomplete="off" />
          <label for="patient-email-input">Adresse e-mail</label>
          <input id="patient-email-input" name="email" type="email" autocomplete="off" />
          <p class="form-error" data-form-error role="alert" hidden></p>
        </div>
        <footer class="modal-footer">
          <button type="button" class="ghost" data-modal-close>Annuler</button>
          <button type="submit" class="primary">Enregistrer</button>
        </footer>
      </form>
    </div>
  `;
  modalHost.appendChild(modalEl);

  formEl = modalEl.querySelector('[data-new-patient-form]');
  nameInput = modalEl.querySelector('#patient-name-input');
  slugInput = modalEl.querySelector('#patient-slug-input');
  emailInput = modalEl.querySelector('#patient-email-input');
  errorEl = modalEl.querySelector('[data-form-error]');
  submitBtn = formEl?.querySelector('button[type="submit"]');

  modalEl.addEventListener('click', (event) => {
    if (event.target === modalEl) {
      closeModal();
    }
  });
  modalEl.querySelectorAll('[data-modal-close]').forEach((btn) => {
    btn.addEventListener('click', (event) => {
      event.preventDefault();
      closeModal();
    });
  });

  if (formEl) {
    formEl.addEventListener('submit', handleSubmit);
  }

  nameInput?.addEventListener('input', handleNameInput);
  slugInput?.addEventListener('input', () => {
    slugDirty = true;
    if (errorEl) {
      errorEl.hidden = true;
      errorEl.textContent = '';
    }
  });
  slugInput?.addEventListener('focus', () => {
    slugDirty = true;
  });
  document.addEventListener('keydown', handleKeyDown);
}

function focusTrap(event) {
  if (!modalEl || event.key !== 'Tab') {
    return;
  }
  const focusable = Array.from(modalEl.querySelectorAll(FOCUSABLE));
  if (!focusable.length) {
    event.preventDefault();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey) {
    if (document.activeElement === first) {
      event.preventDefault();
      last.focus();
    }
  } else if (document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function handleKeyDown(event) {
  if (!active) {
    return;
  }
  if (event.key === 'Escape') {
    event.preventDefault();
    closeModal();
    return;
  }
  if (event.key === 'Tab') {
    focusTrap(event);
  }
}

function showError(message) {
  if (!errorEl) {
    return;
  }
  if (message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  } else {
    errorEl.textContent = '';
    errorEl.hidden = true;
  }
}

function resetForm() {
  slugDirty = false;
  if (formEl) {
    formEl.reset();
  }
  showError('');
}

function openModal() {
  ensureModal();
  if (!modalEl || active) {
    return;
  }
  resetForm();
  modalEl.classList.remove('hidden');
  modalEl.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  active = true;
  const currentName = nameInput?.value || '';
  if (slugInput) {
    slugInput.value = slugify(currentName || 'patient');
  }
  window.setTimeout(() => {
    nameInput?.focus();
  }, 0);
}

export function closeModal() {
  if (!modalEl || !active) {
    return;
  }
  modalEl.classList.add('hidden');
  modalEl.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
  active = false;
  showError('');
  slugDirty = false;
  openerButton?.focus();
}

async function handleSubmit(event) {
  event.preventDefault();
  if (!formEl) {
    return;
  }
  const displayName = nameInput?.value?.trim();
  const slugValue = slugInput?.value?.trim();
  const emailValue = emailInput?.value?.trim();
  if (!displayName) {
    showError('Le nom complet est requis.');
    nameInput?.focus();
    return;
  }
  if (!slugValue) {
    showError("L'identifiant est requis.");
    slugInput?.focus();
    return;
  }
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Création…';
  }
  try {
    await createPatient({ displayName, slug: slugValue, email: emailValue });
    closeModal();
  } catch (error) {
    const message = error?.message || "Impossible d'ajouter le patient.";
    showError(message);
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Enregistrer';
    }
  }
}

function handleNameInput(event) {
  if (!slugInput || slugDirty) {
    return;
  }
  const value = event.target.value || '';
  slugInput.value = slugify(value);
}

export function initNewPatientModal() {
  openerButton = document.querySelector('[data-action="new-patient"]');
  if (!openerButton) {
    return;
  }
  ensureModal();
  openerButton.addEventListener('click', (event) => {
    event.preventDefault();
    openModal();
  });
}
