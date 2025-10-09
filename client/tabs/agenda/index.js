import { jsonGet } from '../../services/api.js';
import { withAssetVersion } from '../../services/assets.js';

const STORAGE_KEY = 'agenda:activeCalendar';

const DIAGNOSTIC_MESSAGES = {
  missing_client_secret:
    'Secret client Google manquant. Ajoutez GOOGLE_CLIENT_SECRET ou importez le fichier client OAuth.',
  redirect_uri_not_registered:
    'URI de redirection non enregistrée. Ajoutez la redirection locale dans la console GCP.',
  invalid_client:
    'Google refuse l’identifiant client. Vérifiez l’ID et le secret OAuth configurés.',
  client_type_installed_not_supported_for_this_redirect:
    'Les identifiants de type “Application installée” ne sont pas compatibles avec ce callback. Générez un client de type Application Web.',
  invalid_client_configuration:
    'Le JSON OAuth est invalide ou incomplet. Téléchargez à nouveau les identifiants depuis la console Google.',
  oauth_exchange_failed:
    'Échec lors de l’échange de jeton OAuth. Revérifiez la configuration et réessayez.',
};

let container;
let initialized = false;

const state = {
  status: null,
  calendars: [],
  events: [],
  selectedCalendarId: null,
  period: getCurrentWeek(),
  loading: false,
};

const elements = {
  toast: null,
  toastMessage: null,
  views: {},
  connectButtons: [],
  disconnectButtons: [],
  refreshButtons: [],
  calendarSelect: null,
  eventsList: null,
  eventsEmpty: null,
  eventsLoading: null,
  periodLabel: null,
  scopesLabel: null,
  redirectLabels: [],
  modeLabel: null,
  docLink: null,
  envList: null,
  secretPath: null,
  diagnostic: null,
};

const weekFormatter = new Intl.DateTimeFormat('fr-FR', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
});

const timeFormatter = new Intl.DateTimeFormat('fr-FR', {
  hour: '2-digit',
  minute: '2-digit',
});

export function init() {
  if (initialized) return;
  container = document.querySelector('section[data-tab="agenda"]');
  if (!container) return;

  ensureStyles();
  loadView()
    .then(() => {
      cacheElements();
      attachEventHandlers();
      applyInitialState();
      checkUrlHints();
      void refreshStatus();
    })
    .catch((err) => {
      console.error('agenda:init failed', err); // eslint-disable-line no-console
    });

  initialized = true;
}

export function show() {
  if (!container) return;
  container.classList.remove('hidden');
  if (!state.loading && state.status?.authenticated) {
    void refreshEvents();
  }
}

export function hide() {
  if (container) {
    container.classList.add('hidden');
  }
}

function ensureStyles() {
  const href = withAssetVersion('/static/tabs/agenda/style.css');
  if (!href) return;
  if (!document.querySelector(`link[data-agenda-style="true"][href="${href}"]`)) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    link.dataset.agendaStyle = 'true';
    document.head.appendChild(link);
  }
}

function loadView() {
  const url = withAssetVersion('/static/tabs/agenda/view.html');
  return fetch(url)
    .then((response) => response.text())
    .then((html) => {
      container.innerHTML = html;
    });
}

function cacheElements() {
  elements.toast = container.querySelector('[data-field="toast"]');
  elements.toastMessage = container.querySelector('[data-field="toast-message"]');
  elements.diagnostic = container.querySelector('[data-field="diagnostic"]');
  elements.views.loading = container.querySelector('[data-view="loading"]');
  elements.views['not-configured'] = container.querySelector('[data-view="not-configured"]');
  elements.views['needs-auth'] = container.querySelector('[data-view="needs-auth"]');
  elements.views.ready = container.querySelector('[data-view="ready"]');
  elements.connectButtons = Array.from(container.querySelectorAll('[data-action="connect"]'));
  elements.disconnectButtons = Array.from(container.querySelectorAll('[data-action="disconnect"]'));
  elements.refreshButtons = Array.from(container.querySelectorAll('[data-action="refresh"]'));
  elements.calendarSelect = container.querySelector('[data-field="calendar-select"]');
  elements.eventsList = container.querySelector('[data-field="events-list"]');
  elements.eventsEmpty = container.querySelector('[data-field="events-empty"]');
  elements.eventsLoading = container.querySelector('[data-field="events-loading"]');
  elements.periodLabel = container.querySelector('[data-field="period-label"]');
  elements.scopesLabel = container.querySelector('[data-field="scopes"]');
  elements.redirectLabels = Array.from(container.querySelectorAll('[data-field="redirect-uri"], [data-field="ready-redirect"]'));
  elements.modeLabel = container.querySelector('[data-field="status-mode"]');
  elements.docLink = container.querySelector('[data-field="doc-link"]');
  elements.envList = container.querySelector('[data-field="env-variables"]');
  elements.secretPath = container.querySelector('[data-field="secret-path"]');
}

function attachEventHandlers() {
  elements.connectButtons.forEach((button) => {
    button.addEventListener('click', () => {
      window.location.assign('/agenda/gcal/auth');
    });
  });

  elements.disconnectButtons.forEach((button) => {
    button.addEventListener('click', () => {
      void disconnect();
    });
  });

  elements.refreshButtons.forEach((button) => {
    button.addEventListener('click', () => {
      void refreshStatus();
    });
  });

  const prev = container.querySelector('[data-action="prev-week"]');
  const next = container.querySelector('[data-action="next-week"]');
  if (prev) {
    prev.addEventListener('click', () => {
      shiftPeriod(-1);
    });
  }
  if (next) {
    next.addEventListener('click', () => {
      shiftPeriod(1);
    });
  }

  if (elements.calendarSelect) {
    elements.calendarSelect.addEventListener('change', () => {
      state.selectedCalendarId = elements.calendarSelect.value || null;
      persistSelectedCalendar();
      void refreshEvents();
    });
  }
}

function applyInitialState() {
  container.dataset.state = 'loading';
  if (elements.docLink) {
    elements.docLink.href = 'https://github.com/assemblee-virtuelle/nouveau-transcripteur/blob/main/README.md#agenda-google';
  }
  if (elements.secretPath) {
    elements.secretPath.textContent = 'instance/gcal_client_secret.json';
  }
  if (elements.envList) {
    elements.envList.textContent = 'GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_SCOPES, GOOGLE_REDIRECT_URI (ou GOOGLE_REDIRECT_BASE)';
  }
  if (elements.diagnostic) {
    elements.diagnostic.classList.add('hidden');
    elements.diagnostic.textContent = '';
  }
  const storedCalendar = getStoredCalendar();
  if (storedCalendar) {
    state.selectedCalendarId = storedCalendar;
  }
  updatePeriodLabel();
  showView('loading');
}

function checkUrlHints() {
  try {
    const url = new URL(window.location.href);
    let needsUpdate = false;
    if (url.searchParams.get('agenda_connected') === '1') {
      showToast('Compte Google connecté avec succès.', 'success');
      url.searchParams.delete('agenda_connected');
      needsUpdate = true;
    }
    if (url.searchParams.get('agenda_disconnected') === '1') {
      showToast('Compte Google déconnecté.', 'info');
      url.searchParams.delete('agenda_disconnected');
      needsUpdate = true;
    }
    if (needsUpdate) {
      window.history.replaceState({}, document.title, url.toString());
    }
  } catch (error) {
    console.error('agenda:url-hint', error); // eslint-disable-line no-console
  }
}

async function refreshStatus() {
  state.loading = true;
  showView('loading');
  showToast('');
  try {
    const response = await jsonGet('/api/agenda/status');
    const status = response?.data || response;
    state.status = status;
    updateStatusDetails(status);
    renderDiagnostic(status);

    if (!status?.configured) {
      state.calendars = [];
      state.events = [];
      showView('not-configured');
      return;
    }

    if (!status.authenticated) {
      state.calendars = [];
      state.events = [];
      showView('needs-auth');
      return;
    }

    await refreshCalendars();
    showView('ready');
    await refreshEvents();
  } catch (error) {
    reportError(error, "Impossible de récupérer l'état de Google Agenda.");
    renderDiagnostic(null);
    showView('not-configured');
  } finally {
    state.loading = false;
  }
}

async function refreshCalendars() {
  try {
    const response = await jsonGet('/api/agenda/calendars');
    const calendars = response?.data || response;
    state.calendars = Array.isArray(calendars)
      ? calendars.map((item) => ({
          id: item.id,
          summary: item.summary || item.id,
          primary: Boolean(item.primary),
        }))
      : [];

    if (!state.calendars.length) {
      state.selectedCalendarId = null;
    } else if (!state.selectedCalendarId || !state.calendars.find((c) => c.id === state.selectedCalendarId)) {
      const primary = state.calendars.find((c) => c.primary);
      state.selectedCalendarId = (primary || state.calendars[0]).id;
    }
    populateCalendarSelect();
    persistSelectedCalendar();
  } catch (error) {
    reportError(error, 'Impossible de charger les calendriers.');
    throw error;
  }
}

async function refreshEvents() {
  if (!state.status?.authenticated || !state.selectedCalendarId) {
    renderEvents([]);
    return;
  }

  setEventsLoading(true);
  const { start, end } = state.period;
  const params = new URLSearchParams({
    calendarId: state.selectedCalendarId,
    timeMin: start.toISOString(),
    timeMax: end.toISOString(),
    maxResults: '2500',
  });

  try {
    const response = await jsonGet(`/api/agenda/events?${params.toString()}`);
    const events = response?.data || response || [];
    const normalized = Array.isArray(events)
      ? events.map((event) => normalizeEvent(event)).filter(Boolean)
      : [];
    state.events = normalized;
    renderEvents(normalized);
  } catch (error) {
    reportError(error, 'Impossible de charger les événements.');
  } finally {
    setEventsLoading(false);
  }
}

async function disconnect() {
  const button = elements.disconnectButtons[0];
  if (button) {
    button.disabled = true;
  }
  try {
    const response = await fetch('/agenda/gcal/disconnect', {
      method: 'POST',
      headers: {
        Accept: 'application/json',
      },
    });
    if (!response.ok) {
      throw new Error("La déconnexion de Google a échoué.");
    }
    showToast('Compte Google déconnecté.', 'info');
  } catch (error) {
    reportError(error, 'Impossible de se déconnecter pour le moment.');
  } finally {
    if (button) {
      button.disabled = false;
    }
    await refreshStatus();
  }
}

function populateCalendarSelect() {
  if (!elements.calendarSelect) return;
  const select = elements.calendarSelect;
  select.innerHTML = '';
  state.calendars.forEach((calendar) => {
    const option = document.createElement('option');
    option.value = calendar.id;
    option.textContent = calendar.primary ? `${calendar.summary} (principal)` : calendar.summary;
    option.selected = calendar.id === state.selectedCalendarId;
    select.appendChild(option);
  });
  select.disabled = state.calendars.length === 0;
}

function renderEvents(events) {
  if (!elements.eventsList || !elements.eventsEmpty) return;
  elements.eventsList.innerHTML = '';
  if (!events.length) {
    elements.eventsEmpty.classList.remove('hidden');
    return;
  }
  elements.eventsEmpty.classList.add('hidden');
  events.forEach((event) => {
    const li = document.createElement('li');
    li.className = 'agenda__event-item';

    const title = document.createElement('strong');
    title.textContent = event.summary || 'Sans titre';
    li.appendChild(title);

    const schedule = document.createElement('p');
    schedule.className = 'agenda__event-schedule';
    schedule.textContent = describeSchedule(event);
    li.appendChild(schedule);

    if (event.attendees?.length) {
      const attendees = document.createElement('p');
      attendees.className = 'agenda__event-attendees';
      attendees.textContent = `Participants : ${event.attendees.map((att) => att.displayName || att.email).join(', ')}`;
      li.appendChild(attendees);
    }

    elements.eventsList.appendChild(li);
  });
}

function normalizeEvent(event) {
  if (!event || typeof event !== 'object') {
    return null;
  }
  const start = event.start || {};
  const end = event.end || {};
  return {
    id: event.id || `${start.dateTime || start.date || ''}-${event.summary || ''}`,
    summary: event.summary || '',
    start,
    end,
    attendees: Array.isArray(event.attendees)
      ? event.attendees
          .filter((attendee) => attendee)
          .map((attendee) => ({
            email: attendee.email || '',
            displayName: attendee.displayName || attendee.email || '',
          }))
      : [],
  };
}

function describeSchedule(event) {
  const start = parseEventDate(event.start);
  const end = parseEventDate(event.end);
  if (!start || !end) {
    return 'Horaire non disponible';
  }

  if (event.start?.date && event.end?.date) {
    return `${capitalize(weekFormatter.format(start))} (toute la journée)`;
  }

  const startDay = capitalize(weekFormatter.format(start));
  const endDay = capitalize(weekFormatter.format(end));
  const startTime = timeFormatter.format(start);
  const endTime = timeFormatter.format(end);

  if (startDay === endDay) {
    return `${startDay} · ${startTime} – ${endTime}`;
  }
  return `${startDay} ${startTime} → ${endDay} ${endTime}`;
}

function parseEventDate(part) {
  if (!part) return null;
  if (part.dateTime) {
    const dt = new Date(part.dateTime);
    return Number.isNaN(dt.getTime()) ? null : dt;
  }
  if (part.date) {
    const dt = new Date(part.date);
    return Number.isNaN(dt.getTime()) ? null : dt;
  }
  return null;
}

function capitalize(str) {
  if (!str) return str;
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function showView(name) {
  container.dataset.state = name;
  Object.entries(elements.views).forEach(([key, node]) => {
    if (!node) return;
    node.classList.toggle('hidden', key !== name);
  });
  const isAuthenticated = name === 'ready';
  const showConnect = name !== 'ready';
  elements.connectButtons.forEach((button) => {
    button.classList.toggle('hidden', !showConnect);
  });
  elements.disconnectButtons.forEach((button) => {
    button.classList.toggle('hidden', !isAuthenticated);
  });
}

function showToast(message, tone = 'info') {
  if (!elements.toast || !elements.toastMessage) return;
  elements.toastMessage.textContent = message || '';
  elements.toast.dataset.tone = tone;
  elements.toast.classList.toggle('hidden', !message);
}

function reportError(error, fallbackMessage) {
  console.error(error); // eslint-disable-line no-console
  const message = error?.message || fallbackMessage || 'Une erreur est survenue.';
  showToast(message, 'error');
}

function updateStatusDetails(status) {
  if (elements.modeLabel) {
    const mode = status?.mode || 'none';
    const label = mode === 'env'
      ? 'Configuration via variables .env'
      : mode === 'file'
      ? 'Configuration via fichier de secrets'
      : 'Aucune configuration détectée';
    const clientType = status?.client_type && status.client_type !== 'unknown' ? ` · Client ${status.client_type}` : '';
    elements.modeLabel.textContent = `${label}${clientType}`;
  }
  if (elements.scopesLabel) {
    const scopes = Array.isArray(status?.scopes) ? status.scopes : [];
    elements.scopesLabel.textContent = scopes.length ? scopes.join(', ') : 'https://www.googleapis.com/auth/calendar.readonly';
  }
  if (elements.redirectLabels.length) {
    const redirectUri = status?.redirect_uri || '';
    elements.redirectLabels.forEach((node) => {
      if (!node) return;
      node.textContent = redirectUri || 'URI de redirection non calculée.';
    });
  }
}

function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderDiagnostic(status) {
  if (!elements.diagnostic) return;
  const shouldShow = status && status.oauth_config_ok === false;
  if (!shouldShow) {
    elements.diagnostic.classList.add('hidden');
    elements.diagnostic.textContent = '';
    return;
  }

  const reasonKey = status.reason || 'unknown';
  const baseMessage = DIAGNOSTIC_MESSAGES[reasonKey] || 'Configuration OAuth incomplète.';
  const redirect = status.redirect_uri ? ` Vérifiez que ${escapeHtml(status.redirect_uri)} est bien enregistrée dans GCP.` : '';
  const missingEnv = Object.entries(status.env_vars_present || {})
    .filter(([, present]) => !present)
    .map(([key]) => key);
  const envAdvice = missingEnv.length ? ` Variables manquantes : ${escapeHtml(missingEnv.join(', '))}.` : '';
  const clientType = status.client_type && status.client_type !== 'unknown' ? ` Type détecté : ${escapeHtml(status.client_type)}.` : '';

  elements.diagnostic.innerHTML = `<strong>Diagnostic OAuth</strong>${escapeHtml(baseMessage)}${redirect}${envAdvice}${clientType}`;
  elements.diagnostic.classList.remove('hidden');
}

function setEventsLoading(isLoading) {
  if (!elements.eventsLoading) return;
  elements.eventsLoading.classList.toggle('hidden', !isLoading);
}

function shiftPeriod(offset) {
  const start = new Date(state.period.start);
  start.setDate(start.getDate() + offset * 7);
  state.period = getCurrentWeek(start);
  updatePeriodLabel();
  void refreshEvents();
}

function updatePeriodLabel() {
  if (!elements.periodLabel) return;
  const { start, end } = state.period;
  const startLabel = capitalize(weekFormatter.format(start));
  const endLabel = capitalize(weekFormatter.format(new Date(end.getTime() - 1)));
  elements.periodLabel.textContent = `${startLabel} → ${endLabel}`;
}

function getStoredCalendar() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored || null;
  } catch (error) {
    console.error('agenda:storage', error); // eslint-disable-line no-console
    return null;
  }
}

function persistSelectedCalendar() {
  try {
    if (state.selectedCalendarId) {
      localStorage.setItem(STORAGE_KEY, state.selectedCalendarId);
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch (error) {
    console.error('agenda:storage-write', error); // eslint-disable-line no-console
  }
}

function getCurrentWeek(anchor = new Date()) {
  const start = new Date(anchor);
  start.setHours(0, 0, 0, 0);
  const day = start.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  start.setDate(start.getDate() + diff);
  const end = new Date(start);
  end.setDate(end.getDate() + 7);
  return { start, end };
}

