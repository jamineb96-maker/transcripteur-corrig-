const VIEW_VERSION = window.ASSET_VERSION || window.__ASSET_VERSION__ || 'ps-research-v2';
const VIEW_URL = `/static/tabs/post_session/view.html?v=${VIEW_VERSION}`;
const STYLE_URL = `/static/tabs/post_session/style.css?v=${VIEW_VERSION}`;

const NAME_REGEX = /^([A-Za-zÀ-ÖØ-öø-ÿ'’\-]+)\s+\d+\b/;
const MAX_PLAN_LINES = 15;
const MAX_AUTO_DIALOG_ENTRIES = 5;

function postJson(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body || {}),
  }).then(async (response) => {
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      /* ignore */
    }
    if (!response.ok) {
      const message = data?.error || data?.message || `HTTP ${response.status}`;
      throw new Error(message);
    }
    return data;
  });
}

const state = {
  transcript: '',
  transcriptUrl: null,
  transcriptMeta: null,
  planText: '',
  planStructured: null,
  pharmaEntries: [],
  selectedPharma: new Set(),
  includePharma: true,
  pharmaMemo: '',
  pharmaBlock: '[PHARMA_MEMO]\n— néant explicite —',
  biblioItems: [],
  selectedBiblio: new Set(),
  includeBiblio: true,
  biblioBlock: '[EXTRAITS BIBLIO]\n– néant explicite –',
  researchCards: [],
  biblioRefs: [],
  promptText: '',
  previousPatient: null,
  autoPatient: null,
  lastFilename: '',
};

const refs = {
  root: null,
  dropzone: null,
  chooseBtn: null,
  fileInput: null,
  autoBadge: null,
  autoBadgeLabel: null,
  autoReset: null,
  progress: null,
  transcript: null,
  cleanTranscript: null,
  segments: null,
  seglist: null,
  plan: null,
  planButton: null,
  pharmaButton: null,
  pharmaTable: null,
  pharmaTextarea: null,
  includePharma: null,
  biblioButton: null,
  biblioList: null,
  biblioTextarea: null,
  includeBiblio: null,
  filterYear: null,
  filterEvidence: null,
  filterDomains: null,
  composeButton: null,
  promptTextarea: null,
  copyPrompt: null,
  exportPrompt: null,
  toast: null,
  patientDialog: null,
  patientDialogOptions: null,
};

let container = null;
let initialized = false;
let toastTimer = null;
let suppressPatientReset = false;

const transcriptWriters = new Set(['api', 'user']);
let currentTranscribe = { id: 0, abort: null };

async function sha256(str) {
  const data = new TextEncoder().encode(typeof str === 'string' ? str : '');
  const buf = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

function mergeSegments(segments) {
  if (!Array.isArray(segments) || !segments.length) return '';
  return segments
    .map((segment) => {
      if (!segment) return '';
      if (typeof segment.text === 'string') return segment.text.trim();
      if (segment.text == null) return '';
      return String(segment.text).trim();
    })
    .filter(Boolean)
    .join('\n');
}

async function verifyAndSelfHeal(candidate, meta) {
  const value = typeof candidate === 'string' ? candidate : '';
  const expectedLenRaw = meta?.text_len ?? meta?.len ?? meta?.textLen;
  const expectedLen = Number.isFinite(Number(expectedLenRaw)) ? Number(expectedLenRaw) : null;
  const expectedSha = meta?.text_sha256 || meta?.sha256 || meta?.textSha256 || null;
  const transcriptUrl = meta?.transcript_url || meta?.transcriptUrl || meta?.url || null;
  const normalized = value.replace(/\r\n/g, '\n');
  const digest = await sha256(normalized);
  const lengthMatches = expectedLen == null ? true : normalized.length === expectedLen;
  const shaMatches = !expectedSha || digest === expectedSha;
  if (lengthMatches && shaMatches) {
    return normalized;
  }

  if (transcriptUrl) {
    try {
      const response = await fetch(transcriptUrl, { cache: 'no-store' });
      if (response.ok) {
        const fresh = (await response.text()).replace(/\r\n/g, '\n');
        const freshDigest = await sha256(fresh);
        const freshLenMatches = expectedLen == null ? true : fresh.length === expectedLen;
        if ((!expectedSha || freshDigest === expectedSha) && freshLenMatches) {
          return fresh;
        }
      }
    } catch (error) {
      console.warn('[transcript] integrity refetch failed', error);
    }
  }

  console.warn('[transcript] integrity mismatch', {
    want: { len: expectedLen, sha: expectedSha, url: transcriptUrl },
    have: { len: normalized.length, sha: digest },
  });
  return normalized;
}

function setTranscript(full, source = 'api') {
  const ta = refs.transcript;
  const value = typeof full === 'string' ? full : '';
  if (ta) {
    ta.removeAttribute('maxlength');
    if (!ta.dataset.maxlengthGuarded) {
      Object.defineProperty(ta, 'maxLength', {
        configurable: true,
        enumerable: true,
        get() {
          return -1;
        },
        set() {},
      });
      ta.dataset.maxlengthGuarded = '1';
    }
    if (ta.value !== value) {
      ta.value = value;
    }
    ta.dataset.locked = '1';
  }
  state.transcript = value;
  console.info('[transcript:set]', source, { len: value.length });
  return value;
}

function guardedWriteTranscript(text, author = 'api') {
  if (!transcriptWriters.has(author)) {
    console.warn('[transcript] write refused for', author);
    return state.transcript || '';
  }
  return setTranscript(text, author);
}

function hardenTranscript() {
  const ta = refs.transcript;
  if (!ta || ta.dataset.hardened === '1') return;
  ta.dataset.hardened = '1';
  const originalSetAttribute = ta.setAttribute.bind(ta);
  ta.setAttribute = function setAttributeGuard(key, value) {
    if (String(key).toLowerCase() === 'maxlength') {
      return undefined;
    }
    return originalSetAttribute(key, value);
  };
  ta.addEventListener(
    'input',
    (event) => {
      if (ta.dataset.locked === '1' && !event.isTrusted) {
        event.stopImmediatePropagation();
        if (ta.value.length < (state.transcript?.length || 0)) {
          ta.value = state.transcript || '';
        }
        console.warn('[transcript] blocked non-trusted input rewrite');
      }
    },
    true,
  );
}

function ensureStyle() {
  if (document.querySelector('link[data-ps-style="true"]')) {
    return;
  }
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLE_URL;
  link.dataset.psStyle = 'true';
  document.head.appendChild(link);
}

function toast(message, tone = 'info') {
  if (!refs.toast) return;
  refs.toast.textContent = message;
  refs.toast.dataset.tone = tone;
  refs.toast.dataset.visible = 'true';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    refs.toast.dataset.visible = 'false';
  }, 3600);
}

function setBusy(button, busy) {
  if (!button) return;
  if (busy) {
    button.disabled = true;
    button.dataset.busy = 'true';
    button.setAttribute('aria-busy', 'true');
  } else {
    button.disabled = false;
    button.dataset.busy = 'false';
    button.removeAttribute('aria-busy');
  }
}

function showProgress(visible) {
  if (!refs.progress) return;
  refs.progress.hidden = !visible;
  refs.progress.setAttribute('aria-hidden', visible ? 'false' : 'true');
}

function copyToClipboard(value) {
  if (!value) {
    toast('Rien à copier.', 'warn');
    return;
  }
  navigator.clipboard
    .writeText(value)
    .then(() => toast('Copié dans le presse-papiers.', 'success'))
    .catch(() => toast('Impossible de copier le contenu.', 'error'));
}

function getPatientSelect() {
  return document.getElementById('patientSelect');
}

function getSelectedPatientId() {
  return getPatientSelect()?.value || '';
}

function dispatchPatientChange(select) {
  if (!select) return;
  const event = new Event('change', { bubbles: true });
  select.dispatchEvent(event);
}

function setSelectedPatient(id) {
  const select = getPatientSelect();
  if (!select) return false;
  if (id) {
    if (select.value === id) {
      return true;
    }
    select.value = id;
  } else {
    select.value = '';
  }
  dispatchPatientChange(select);
  return true;
}

function normalizeName(value) {
  return (value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();
}

function primaryFirstname(value) {
  const normalized = normalizeName(value);
  if (!normalized) return '';
  const match = normalized.match(/^[^\s]+/u);
  return match ? match[0] : normalized;
}

function levenshtein(a, b, maxDistance = 1) {
  if (a === b) return 0;
  if (!a) return b.length;
  if (!b) return a.length;
  if (Math.abs(a.length - b.length) > maxDistance) {
    return maxDistance + 1;
  }
  const previous = new Array(b.length + 1);
  for (let j = 0; j <= b.length; j += 1) {
    previous[j] = j;
  }
  for (let i = 1; i <= a.length; i += 1) {
    const current = [i];
    let rowMin = maxDistance + 1;
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      const insertCost = current[j - 1] + 1;
      const deleteCost = previous[j] + 1;
      const replaceCost = previous[j - 1] + cost;
      const cell = Math.min(insertCost, deleteCost, replaceCost);
      current[j] = cell;
      if (cell < rowMin) {
        rowMin = cell;
      }
    }
    if (rowMin > maxDistance) {
      return maxDistance + 1;
    }
    for (let j = 0; j <= b.length; j += 1) {
      previous[j] = current[j];
    }
  }
  return previous[b.length];
}

function extractFirstname(filename) {
  if (typeof filename !== 'string') return '';
  const match = NAME_REGEX.exec(filename.trim());
  return match ? match[1] : '';
}

function matchLocalPatient(firstname) {
  const candidate = primaryFirstname(firstname);
  if (!candidate) return [];
  const select = getPatientSelect();
  if (!select) return [];
  const exact = [];
  const fuzzy = [];
  const seen = new Set();
  const options = Array.from(select.options || []);
  options.forEach((option) => {
    if (!option?.value || seen.has(option.value)) return;
    const label = option.textContent || '';
    const first = primaryFirstname(label);
    if (!first) return;
    const match = {
      id: option.value,
      display: label,
      email: option.dataset?.email || '',
    };
    if (first === candidate) {
      exact.push(match);
      seen.add(option.value);
      return;
    }
    if (levenshtein(first, candidate, 1) <= 1) {
      fuzzy.push(match);
      seen.add(option.value);
    }
  });
  const pool = exact.length ? exact : fuzzy;
  return pool.slice(0, MAX_AUTO_DIALOG_ENTRIES);
}

function showAutoBadge(match, filename) {
  if (!refs.autoBadge || !refs.autoBadgeLabel) return;
  const source = filename ? ` (depuis « ${filename} »)` : '';
  const label = match?.email ? `${match.display} (${match.email})` : match?.display || '';
  refs.autoBadgeLabel.textContent = `Patient auto-sélectionné : ${label}${source}`;
  refs.autoBadge.hidden = false;
}

function hideAutoBadge() {
  if (refs.autoBadge) {
    refs.autoBadge.hidden = true;
  }
  state.autoPatient = null;
}

function applyAutoSelection(match, filename, origin) {
  if (!match?.id) return;
  if (!state.previousPatient) {
    state.previousPatient = getSelectedPatientId() || null;
  }
  let applied = false;
  const previousSuppress = suppressPatientReset;
  suppressPatientReset = true;
  try {
    applied = setSelectedPatient(match.id);
  } finally {
    suppressPatientReset = previousSuppress;
  }
  if (applied) {
    state.autoPatient = {
      id: match.id,
      display: match.display,
      email: match.email || '',
      filename,
      origin,
    };
    console.info('[post-session] auto patient', { candidate: match.display, filename, origin });
    showAutoBadge(match, filename);
  }
}

async function resolvePatientServer(firstname) {
  const url = `/api/patients/resolve?firstname=${encodeURIComponent(firstname)}`;
  try {
    const response = await fetch(url, { headers: { Accept: 'application/json' } });
    const data = await response.json().catch(() => ({ matches: [] }));
    if (response.ok && Array.isArray(data?.matches)) {
      return data.matches;
    }
  } catch (error) {
    console.warn('[post-session] patient resolve failed', error);
  }
  return [];
}

function renderPatientDialog(matches) {
  if (!refs.patientDialog || !refs.patientDialogOptions) return;
  refs.patientDialogOptions.innerHTML = '';
  matches.slice(0, MAX_AUTO_DIALOG_ENTRIES).forEach((match, index) => {
    const wrapper = document.createElement('label');
    wrapper.className = 'ps-dialog-option';
    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = 'auto-patient-choice';
    radio.value = match.id;
    if (index === 0) radio.checked = true;
    const span = document.createElement('span');
    span.textContent = match.display;
    if (match.email) {
      const email = document.createElement('small');
      email.textContent = match.email;
      email.className = 'ps-dialog-email';
      span.appendChild(document.createElement('br'));
      span.appendChild(email);
    }
    wrapper.appendChild(radio);
    wrapper.appendChild(span);
    refs.patientDialogOptions.appendChild(wrapper);
  });
}

async function showPatientDialog(matches, filename) {
  if (!refs.patientDialog) return null;
  const limited = Array.isArray(matches) ? matches.slice(0, MAX_AUTO_DIALOG_ENTRIES) : [];
  renderPatientDialog(limited);
  const dialog = refs.patientDialog;
  return new Promise((resolve) => {
    const handleClose = () => {
      dialog.removeEventListener('close', handleClose);
      const value = dialog.returnValue;
      if (value === 'confirm') {
        const chosen = dialog.querySelector('input[name="auto-patient-choice"]:checked');
        if (chosen) {
          const match = limited.find((item) => item.id === chosen.value);
          if (match) {
            applyAutoSelection(match, filename, 'dialog');
            resolve(match);
            return;
          }
        }
      }
      resolve(null);
    };
    dialog.addEventListener('close', handleClose, { once: true });
    try {
      dialog.showModal();
    } catch (error) {
      dialog.removeEventListener('close', handleClose);
      console.warn('[post-session] patient dialog', error);
      resolve(null);
    }
  });
}

async function attemptAutoPatient(candidate, filename) {
  if (!candidate) return;
  const localMatches = matchLocalPatient(candidate);
  if (localMatches.length === 1) {
    applyAutoSelection(localMatches[0], filename, 'local');
    return;
  }
  const remoteMatches = await resolvePatientServer(candidate);
  if (remoteMatches.length === 1) {
    applyAutoSelection(remoteMatches[0], filename, 'api');
    return;
  }
  if (remoteMatches.length > 1) {
    await showPatientDialog(remoteMatches, filename);
  } else {
    console.info('[post-session] auto patient aucune correspondance', { candidate, filename });
    hideAutoBadge();
  }
}

function updatePharmaBlock() {
  if (state.pharmaMemo) {
    state.pharmaBlock = ['[PHARMA_MEMO]', state.pharmaMemo].join('\n');
  } else {
    state.pharmaBlock = '[PHARMA_MEMO]\n— néant explicite —';
  }
  if (refs.pharmaTextarea) {
    refs.pharmaTextarea.value = state.pharmaBlock;
  }
}

function updateBiblioBlock() {
  const selected = state.biblioItems.filter((entry) => state.selectedBiblio.has(entry.id));
  if (selected.length) {
    const refs = selected.map((entry) => entry.refLine || entry.line || entry.title || '');
    const lines = refs.map((ref) => (ref.startsWith('–') ? ref : `– ${ref}`));
    state.biblioBlock = ['[EXTRAITS BIBLIO]', ...lines].join('\n');
  } else {
    state.biblioBlock = '[EXTRAITS BIBLIO]\n– néant explicite –';
  }
  if (refs.biblioTextarea) {
    refs.biblioTextarea.value = state.biblioBlock;
  }
}

function renderPharma(payload) {
  if (!refs.pharmaTable) return;
  const entries = Array.isArray(payload?.entries)
    ? payload.entries
    : Array.isArray(payload?.molecules)
    ? payload.molecules
    : [];
  refs.pharmaTable.innerHTML = '';
  state.selectedPharma = new Set();
  state.pharmaEntries = entries;
  entries.forEach((entry) => {
    const name = entry.dci || entry.name || '';
    const row = document.createElement('tr');
    const includeCell = document.createElement('td');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.dataset.name = name;
    checkbox.checked = true;
    checkbox.disabled = true;
    includeCell.appendChild(checkbox);
    const nameCell = document.createElement('td');
    nameCell.textContent = name ? name.charAt(0).toUpperCase() + name.slice(1) : '—';
    const classCell = document.createElement('td');
    classCell.textContent = entry.classe || entry.class || '—';
    const infoCell = document.createElement('td');
    const infoParts = [];
    const mecanisme = entry.mecanisme || entry.mechanism;
    if (mecanisme) infoParts.push(`Mécanisme: ${mecanisme}`);
    const demiVie = entry.demi_vie || entry.half_life;
    if (demiVie) infoParts.push(`Demi-vie: ${demiVie}`);
    const ei = Array.isArray(entry.effets_frequents) ? entry.effets_frequents : entry.common;
    if (ei && ei.length) infoParts.push(`EI: ${ei.slice(0, 3).join(', ')}`);
    const rdr = Array.isArray(entry.rdr) ? entry.rdr : [];
    if (rdr && rdr.length) infoParts.push(`RDR: ${rdr.slice(0, 3).join(', ')}`);
    infoCell.textContent = infoParts.join(' · ') || '—';
    row.appendChild(includeCell);
    row.appendChild(nameCell);
    row.appendChild(classCell);
    row.appendChild(infoCell);
    refs.pharmaTable.appendChild(row);
    if (name) state.selectedPharma.add(name);
  });
  const memo = typeof payload?.memo === 'string' ? payload.memo.trim() : '';
  state.pharmaMemo = memo;
  const block = payload?.pharma_block || payload?.export_block;
  if (block) {
    state.pharmaBlock = block;
    if (!state.pharmaMemo) {
      state.pharmaMemo = block.split('\n').slice(1).join('\n').trim();
    }
  }
  updatePharmaBlock();
  updateButtons();
}

function renderBiblio(payload) {
  if (!refs.biblioList) return;
  const cards = Array.isArray(payload?.cards)
    ? payload.cards
    : Array.isArray(payload)
    ? payload
    : [];
  const refsList = Array.isArray(payload?.biblio) ? payload.biblio : [];
  refs.biblioList.innerHTML = '';
  state.researchCards = cards;
  state.biblioRefs = refsList;
  state.biblioItems = cards.map((card, index) => {
    const source = card.source || {};
    const id = card.id || source.url || `${source.ref || 'card'}:${index}`;
    const refLine = refsList[index] || `${source.auteurs || 'Auteur inconnu'} (${source.annee || source.year || 's.d.'}). ${source.ref || card.these || ''}.`;
    return {
      id,
      title: card.these || 'Carte clinique',
      citation: card.citation_courte || '',
      implications: Array.isArray(card.implications) ? card.implications : [],
      limite: card.limite || '',
      source,
      refLine,
    };
  });
  state.selectedBiblio = new Set();
  state.biblioItems.forEach((item) => {
    const li = document.createElement('li');
    li.className = 'ps-biblio-item';
    const label = document.createElement('label');
    label.className = 'ps-biblio-label';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.dataset.id = item.id;
    checkbox.checked = true;
    const title = document.createElement('strong');
    title.textContent = item.title.replace(/^–\s*/, '') || 'Carte clinique';
    label.appendChild(checkbox);
    label.appendChild(title);
    li.appendChild(label);
    if (item.citation) {
      const citation = document.createElement('p');
      citation.className = 'ps-biblio-excerpt';
      citation.textContent = item.citation;
      li.appendChild(citation);
    }
    const metaParts = [];
    const auteurs = item.source?.auteurs || '';
    const annee = item.source?.annee || item.source?.year || '';
    const ref = item.source?.ref || '';
    if (auteurs) metaParts.push(auteurs);
    if (annee) metaParts.push(`(${annee})`);
    if (ref) metaParts.push(ref);
    if (metaParts.length) {
      const meta = document.createElement('p');
      meta.className = 'ps-biblio-meta';
      meta.textContent = metaParts.join(' ');
      li.appendChild(meta);
    }
    refs.biblioList.appendChild(li);
    state.selectedBiblio.add(item.id);
  });
  if (payload?.biblio_block) {
    state.biblioBlock = payload.biblio_block;
  }
  updateBiblioBlock();
  updateButtons();
}

function enforcePlanCap() {
  if (!refs.plan) return;
  const value = refs.plan.value || '';
  const lines = value.split(/\r?\n/);
  if (lines.length > MAX_PLAN_LINES) {
    refs.plan.value = lines.slice(0, MAX_PLAN_LINES).join('\n');
  }
  state.planText = refs.plan.value.trim();
  updateButtons();
}

function updateButtons() {
  if (refs.planButton) {
    refs.planButton.disabled = !(state.transcript && state.transcript.length > 10);
  }
  const hasContext = Boolean(state.planText || state.transcript);
  if (refs.pharmaButton) {
    refs.pharmaButton.disabled = !hasContext;
  }
  if (refs.biblioButton) {
    refs.biblioButton.disabled = !hasContext;
  }
  if (refs.composeButton) {
    const ready = Boolean(state.planText && state.transcript);
    refs.composeButton.disabled = !ready;
  }
  if (refs.copyPrompt) {
    refs.copyPrompt.disabled = !state.promptText;
  }
  if (refs.exportPrompt) {
    refs.exportPrompt.disabled = !state.promptText;
  }
}

async function fetchPlanText(transcript) {
  return postJson('/api/post/research/plan_v2', { transcript });
}

async function fetchPharmaBlock(transcript, planText) {
  return postJson('/api/post/research/pharma', { transcript, plan_text: planText });
}

async function fetchBiblioBlock(transcript, planText, filters) {
  return postJson('/api/post/research/library', {
    transcript,
    plan_text: planText,
    max_items: 10,
    filters,
  });
}

async function composeResearchPrompt(transcript, planText, pharmaBlock, biblioBlock) {
  return postJson('/api/post/research/compose', {
    transcript,
    plan_text: planText,
    pharma_block: pharmaBlock,
    biblio_block: biblioBlock,
  });
}

function handleTranscriptInput() {
  state.transcript = refs.transcript.value || '';
  state.transcriptUrl = null;
  state.transcriptMeta = null;
  updateButtons();
}

function handleCleanTranscript() {
  if (!refs.transcript) return;
  const value = refs.transcript.value || '';
  const cleaned = value
    .replace(/\s{2,}/g, ' ')
    .replace(/\s+([,;:.!?])/g, '$1 ')
    .replace(/([,;:.!?])(\S)/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .replace(/\s([?!.,;:])/g, '$1')
    .trim();
  guardedWriteTranscript(cleaned, 'user');
  state.transcriptUrl = null;
  state.transcriptMeta = null;
  updateButtons();
}

async function handleGeneratePlan() {
  if (!state.transcript) {
    toast('Ajoutez un transcript.', 'warn');
    return;
  }
  setBusy(refs.planButton, true);
  try {
    const payload = await fetchPlanText(state.transcript);
    const planText = payload?.plan_text || '';
    state.planText = planText;
    state.planStructured = payload?.plan_structured || null;
    if (refs.plan) refs.plan.value = planText;
    enforcePlanCap();
    let researchDone = false;
    try {
      const filters = gatherFilters();
      const researchPayload = await fetchBiblioBlock(state.transcript, planText, filters);
      renderBiblio(researchPayload || {});
      researchDone = true;
    } catch (error) {
      console.error('[post-session] unified research', error);
    }
    if (researchDone) {
      toast('Résumé clinique et recherche actualisés.');
    } else {
      toast('Résumé clinique généré. Recherche indisponible.', 'warn');
    }
  } catch (error) {
    console.error('[post-session] plan_v2', error);
    toast(error.message || 'Plan court indisponible.', 'error');
  } finally {
    setBusy(refs.planButton, false);
    updateButtons();
  }
}

function gatherFilters() {
  const minYearRaw = refs.filterYear?.value?.trim();
  const minYear = minYearRaw ? Number.parseInt(minYearRaw, 10) : null;
  const evidence = refs.filterEvidence?.value?.trim() || null;
  const domainsRaw = refs.filterDomains?.value || '';
  const domains = domainsRaw
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  return {
    min_year: Number.isNaN(minYear) ? null : minYear,
    min_evidence: evidence || null,
    domains,
  };
}

async function handleRunPharma() {
  if (!state.transcript && !state.planText) {
    toast('Ajoutez un transcript ou un résumé clinique.', 'warn');
    return;
  }
  setBusy(refs.pharmaButton, true);
  try {
    const payload = await fetchPharmaBlock(state.transcript, state.planText);
    renderPharma(payload || {});
    toast('Analyse pharmacologique terminée.');
  } catch (error) {
    console.error('[post-session] research pharma', error);
    toast(error.message || 'Analyse pharmacologique indisponible.', 'error');
  } finally {
    setBusy(refs.pharmaButton, false);
  }
}

async function handleRunBiblio() {
  if (!state.transcript && !state.planText) {
    toast('Ajoutez un transcript ou un résumé clinique.', 'warn');
    return;
  }
  setBusy(refs.biblioButton, true);
  try {
    const filters = gatherFilters();
    const payload = await fetchBiblioBlock(state.transcript, state.planText, filters);
    renderBiblio(payload || {});
    toast('Extraits bibliographiques récupérés.');
  } catch (error) {
    console.error('[post-session] research biblio', error);
    toast(error.message || 'Bibliothèque indisponible.', 'error');
  } finally {
    setBusy(refs.biblioButton, false);
  }
}

async function handleComposePrompt() {
  if (!state.planText) {
    toast('Générez ou collez un résumé clinique.', 'warn');
    return;
  }
  if (!state.transcript) {
    toast('Ajoutez un transcript intégral.', 'warn');
    return;
  }
  const pharmaBlock = state.includePharma ? state.pharmaBlock : '';
  const biblioBlock = state.includeBiblio ? state.biblioBlock : '';
  setBusy(refs.composeButton, true);
  try {
    const payload = await composeResearchPrompt(state.transcript, state.planText, pharmaBlock, biblioBlock);
    state.promptText = payload?.prompt || '';
    if (refs.promptTextarea) {
      refs.promptTextarea.value = state.promptText;
    }
    updateButtons();
    toast('Méga-prompt composé.');
  } catch (error) {
    console.error('[post-session] compose prompt', error);
    toast(error.message || 'Impossible de composer le méga-prompt.', 'error');
  } finally {
    setBusy(refs.composeButton, false);
  }
}

function handlePharmaToggle(event) {
  if (event.target?.dataset?.name == null) return;
  const name = event.target.dataset.name;
  if (!name) return;
  if (event.target.checked) {
    state.selectedPharma.add(name);
  } else {
    state.selectedPharma.delete(name);
  }
  updatePharmaBlock();
  updateButtons();
}

function handleBiblioToggle(event) {
  if (!event.target?.dataset?.id) return;
  const id = event.target.dataset.id;
  if (event.target.checked) {
    state.selectedBiblio.add(id);
  } else {
    state.selectedBiblio.delete(id);
  }
  updateBiblioBlock();
  updateButtons();
}

function handleIncludePharmaChange() {
  state.includePharma = Boolean(refs.includePharma?.checked);
  updateButtons();
}

function handleIncludeBiblioChange() {
  state.includeBiblio = Boolean(refs.includeBiblio?.checked);
  updateButtons();
}

function resetState(options = {}) {
  const preserveTranscript = Boolean(options && options.preserveTranscript);
  if (!preserveTranscript) {
    guardedWriteTranscript('', 'api');
    state.transcriptUrl = null;
    state.transcriptMeta = null;
  }
  state.planText = '';
  state.planStructured = null;
  state.pharmaEntries = [];
  state.selectedPharma = new Set();
  state.pharmaMemo = '';
  state.pharmaBlock = '[PHARMA_MEMO]\n— néant explicite —';
  state.biblioItems = [];
  state.selectedBiblio = new Set();
  state.biblioBlock = '[EXTRAITS BIBLIO]\n– néant explicite –';
  state.researchCards = [];
  state.biblioRefs = [];
  state.promptText = '';
  if (refs.plan) refs.plan.value = '';
  if (refs.pharmaTextarea) refs.pharmaTextarea.value = state.pharmaBlock;
  if (refs.biblioTextarea) refs.biblioTextarea.value = state.biblioBlock;
  if (refs.promptTextarea) refs.promptTextarea.value = '';
  renderPharma({ entries: [] });
  renderBiblio({ cards: [], biblio: [] });
  updateButtons();
}

function handlePatientChanged() {
  if (!suppressPatientReset && !state.autoPatient) {
    state.previousPatient = getSelectedPatientId() || null;
  }
  hideAutoBadge();
  resetState({ preserveTranscript: suppressPatientReset });
}

function updateSegments(segments) {
  if (!refs.seglist) return;
  refs.seglist.innerHTML = '';
  if (!Array.isArray(segments) || !segments.length) return;
  segments.forEach((segment) => {
    const div = document.createElement('div');
    div.className = 'seg';
    const start = Number(segment.start || 0).toFixed(1);
    const end = Number(segment.end || 0).toFixed(1);
    div.textContent = `[${start} – ${end}] ${segment.text || ''}`.trim();
    refs.seglist.appendChild(div);
  });
}

async function doTranscribe(file) {
  if (!file) return;
  const patient = getSelectedPatientId();
  if (!patient) {
    toast('Sélectionnez un·e patient·e avant de transcrire.', 'warn');
    return;
  }
  currentTranscribe.abort?.abort?.();
  currentTranscribe.id += 1;
  const id = currentTranscribe.id;
  const controller = new AbortController();
  currentTranscribe.abort = controller;
  console.info('[post-session] upload', { name: file.name, size: file.size });
  const formData = new FormData();
  formData.append('file', file);
  formData.append('patient', patient);
  showProgress(true);
  setBusy(refs.chooseBtn, true);
  try {
    const response = await fetch('/api/post/transcribe', {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });
    const payload = await response.json();
    if (id !== currentTranscribe.id) {
      return;
    }
    if (!response.ok || (!payload?.ok && !payload?.success)) {
      throw new Error(payload?.error?.message || payload?.error || 'Transcription échouée.');
    }
    const data = payload?.data && typeof payload.data === 'object' ? payload.data : payload;
    const segments = Array.isArray(data?.segments) ? data.segments : [];
    const transcriptMeta = {
      text_len: Number.isFinite(Number(data?.text_len ?? data?.textLen))
        ? Number(data?.text_len ?? data?.textLen)
        : null,
      text_sha256: typeof data?.text_sha256 === 'string'
        ? data.text_sha256
        : typeof data?.textSha256 === 'string'
        ? data.textSha256
        : null,
      transcript_url: data?.transcript_url || data?.transcriptUrl || null,
    };
    const mergedSegmentsText = mergeSegments(segments).replace(/\r\n/g, '\n');
    const transcriptUrl = transcriptMeta.transcript_url;
    const inlineCandidate =
      typeof data?.text === 'string'
        ? data.text
        : typeof data?.transcript === 'string'
        ? data.transcript
        : '';
    const inlineNormalized = typeof inlineCandidate === 'string' ? inlineCandidate.replace(/\r\n/g, '\n') : '';
    const preferredInline =
      mergedSegmentsText.length > inlineNormalized.length ? mergedSegmentsText : inlineNormalized;

    let healed = await verifyAndSelfHeal(preferredInline, transcriptMeta);
    if (id !== currentTranscribe.id) {
      return;
    }

    guardedWriteTranscript(healed, 'api');
    if (refs.transcript) {
      const domVerified = await verifyAndSelfHeal(refs.transcript.value, transcriptMeta);
      if (domVerified !== refs.transcript.value) {
        guardedWriteTranscript(domVerified, 'api');
        healed = domVerified;
      } else {
        healed = domVerified;
      }
    }

    state.transcriptUrl = transcriptUrl || null;
    state.transcriptMeta = {
      url: transcriptUrl || null,
      len: transcriptMeta.text_len ?? healed.length,
      sha256: transcriptMeta.text_sha256 || null,
    };
    if (transcriptMeta.text_len == null) {
      transcriptMeta.text_len = state.transcriptMeta.len;
    }
    if (!transcriptMeta.text_sha256 && state.transcriptMeta.sha256) {
      transcriptMeta.text_sha256 = state.transcriptMeta.sha256;
    }

    const domValue = refs.transcript ? refs.transcript.value : healed;
    const domLen = domValue.length;
    const domSha = await sha256(domValue);
    console.info('[post-session/ui] transcript integrity', {
      expectedLen: state.transcriptMeta.len,
      domLen,
      expectedSha: state.transcriptMeta.sha256,
      domSha,
    });

    updateSegments(segments);
    state.lastFilename = file.name;
    const autoData = data?.auto_patient;
    if (autoData?.candidate && Array.isArray(autoData.matches) && !state.autoPatient) {
      if (autoData.matches.length === 1) {
        applyAutoSelection(autoData.matches[0], file.name, 'server');
      } else if (autoData.matches.length > 1) {
        await showPatientDialog(autoData.matches, file.name);
      }
    }
    toast('Transcription terminée.');
    setTimeout(async () => {
      if (id !== currentTranscribe.id) return;
      const ta = refs.transcript;
      if (!ta) return;
      if (ta.value.length < healed.length) {
        console.warn('[transcript] late shrink detected; restoring');
        const restored = await verifyAndSelfHeal(ta.value, transcriptMeta);
        if (id !== currentTranscribe.id) return;
        guardedWriteTranscript(restored, 'api');
        state.transcriptMeta = {
          url: transcriptUrl || null,
          len: transcriptMeta.text_len ?? restored.length,
          sha256: transcriptMeta.text_sha256 || null,
        };
        if (transcriptMeta.text_len == null || transcriptMeta.text_len !== state.transcriptMeta.len) {
          transcriptMeta.text_len = state.transcriptMeta.len;
        }
        if (!transcriptMeta.text_sha256 && state.transcriptMeta.sha256) {
          transcriptMeta.text_sha256 = state.transcriptMeta.sha256;
        }
      }
    }, 500);
  } catch (error) {
    if (error?.name === 'AbortError') {
      console.info('[post-session] transcription aborted');
      return;
    }
    console.error('[post-session] transcription', error);
    toast(error.message || 'Transcription impossible.', 'error');
  } finally {
    if (id === currentTranscribe.id) {
      showProgress(false);
      setBusy(refs.chooseBtn, false);
    }
    if (refs.fileInput) refs.fileInput.value = '';
    updateButtons();
  }
}

async function handleFileSelection(file) {
  if (!file) return;
  const firstname = extractFirstname(file.name || '');
  if (firstname) {
    await attemptAutoPatient(firstname, file.name);
  } else {
    hideAutoBadge();
  }
  await doTranscribe(file);
}

function bindFileInputs() {
  if (!refs.dropzone || !refs.fileInput || !refs.chooseBtn) return;
  const dz = refs.dropzone;
  const input = refs.fileInput;
  const prevent = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };
  ['dragenter', 'dragover'].forEach((type) => {
    dz.addEventListener(type, (event) => {
      prevent(event);
      dz.classList.add('hover');
    });
  });
  ['dragleave', 'drop'].forEach((type) => {
    dz.addEventListener(type, (event) => {
      prevent(event);
      dz.classList.remove('hover');
    });
  });
  dz.addEventListener('drop', (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      void handleFileSelection(file);
    }
  });
  refs.chooseBtn.addEventListener('click', () => input.click());
  dz.addEventListener('click', () => input.click());
  input.addEventListener('change', () => {
    const file = input.files?.[0];
    if (file) {
      void handleFileSelection(file);
    }
  });
}

function bindEvents() {
  bindFileInputs();
  if (refs.transcript) {
    refs.transcript.addEventListener('input', handleTranscriptInput);
    refs.transcript.addEventListener('keydown', (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        void handleGeneratePlan();
      }
    });
  }
  if (refs.cleanTranscript) {
    refs.cleanTranscript.addEventListener('click', handleCleanTranscript);
  }
  if (refs.plan) {
    refs.plan.addEventListener('input', enforcePlanCap);
  }
  if (refs.planButton) {
    refs.planButton.addEventListener('click', () => void handleGeneratePlan());
  }
  if (refs.pharmaButton) {
    refs.pharmaButton.addEventListener('click', () => void handleRunPharma());
  }
  if (refs.biblioButton) {
    refs.biblioButton.addEventListener('click', () => void handleRunBiblio());
  }
  if (refs.composeButton) {
    refs.composeButton.addEventListener('click', () => void handleComposePrompt());
  }
  if (refs.pharmaTable) {
    refs.pharmaTable.addEventListener('change', handlePharmaToggle);
  }
  if (refs.includePharma) {
    refs.includePharma.addEventListener('change', handleIncludePharmaChange);
  }
  if (refs.biblioList) {
    refs.biblioList.addEventListener('change', handleBiblioToggle);
  }
  if (refs.includeBiblio) {
    refs.includeBiblio.addEventListener('change', handleIncludeBiblioChange);
  }
  if (refs.copyPrompt) {
    refs.copyPrompt.addEventListener('click', () => copyToClipboard(state.promptText));
  }
  if (refs.exportPrompt) {
    refs.exportPrompt.addEventListener('click', () => {
      if (!state.promptText) {
        toast('Méga-prompt vide.', 'warn');
        return;
      }
      const blob = new Blob([state.promptText], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'post-session-prompt.txt';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      toast('Fichier exporté.', 'success');
    });
  }
  if (refs.autoReset) {
    refs.autoReset.addEventListener('click', () => {
      const previous = state.previousPatient;
      hideAutoBadge();
      if (previous) {
        const previousSuppress = suppressPatientReset;
        suppressPatientReset = true;
        try {
          setSelectedPatient(previous);
        } finally {
          suppressPatientReset = previousSuppress;
        }
      }
    });
  }
  window.addEventListener('patient:changed', handlePatientChanged);
}

function mapRefs() {
  refs.root = container.querySelector('[data-ps-root]');
  refs.dropzone = container.querySelector('#ps-drop');
  refs.chooseBtn = container.querySelector('#ps-choose');
  refs.fileInput = container.querySelector('#ps-file');
  refs.autoBadge = container.querySelector('#ps-auto-badge');
  refs.autoBadgeLabel = container.querySelector('#ps-auto-badge span[data-badge-label]');
  refs.autoReset = container.querySelector('#ps-auto-reset');
  refs.progress = container.querySelector('#ps-progress');
  refs.transcript = container.querySelector('#ps-transcript');
  refs.cleanTranscript = container.querySelector('#ps-clean-transcript');
  refs.segments = container.querySelector('#ps-segments');
  refs.seglist = container.querySelector('#ps-seglist');
  refs.plan = container.querySelector('#ps-plan-text');
  refs.planButton = container.querySelector('#ps-make-plan');
  refs.pharmaButton = container.querySelector('#ps-run-pharma');
  refs.pharmaTable = container.querySelector('#ps-pharma-rows');
  refs.pharmaTextarea = container.querySelector('#ps-pharma-text');
  refs.includePharma = container.querySelector('#ps-include-pharma');
  refs.biblioButton = container.querySelector('#ps-run-biblio');
  refs.biblioList = container.querySelector('#ps-biblio-list');
  refs.biblioTextarea = container.querySelector('#ps-biblio-text');
  refs.includeBiblio = container.querySelector('#ps-include-biblio');
  refs.filterYear = container.querySelector('#ps-filter-year');
  refs.filterEvidence = container.querySelector('#ps-filter-evidence');
  refs.filterDomains = container.querySelector('#ps-filter-domains');
  refs.composeButton = container.querySelector('#ps-compose');
  refs.promptTextarea = container.querySelector('#ps-prompt-text');
  refs.copyPrompt = container.querySelector('#ps-copy-prompt');
  refs.exportPrompt = container.querySelector('#ps-export-prompt');
  refs.toast = container.querySelector('#ps-toast');
  refs.patientDialog = container.querySelector('#ps-patient-dialog');
  refs.patientDialogOptions = container.querySelector('#ps-patient-options');
}

async function mountView() {
  ensureStyle();
  try {
    const response = await fetch(VIEW_URL, { headers: { Accept: 'text/html' } });
    const html = await response.text();
    container.innerHTML = html;
    mapRefs();
    hardenTranscript();
    bindEvents();
    updateButtons();
  } catch (error) {
    console.error('[post-session] init failed', error);
    container.innerHTML = '<p class="ps-error">Impossible de charger le module Post-séance.</p>';
  }
}

export function init() {
  if (initialized) return;
  container = document.querySelector('section[data-tab="post_session"]');
  if (!container) return;
  initialized = true;
  void mountView();
}

export function show() {
  if (!container) return;
  container.classList.remove('hidden');
  updateButtons();
}

export function hide() {
  if (!container) return;
  container.classList.add('hidden');
}

export function destroy() {
  window.removeEventListener('patient:changed', handlePatientChanged);
  if (toastTimer) clearTimeout(toastTimer);
  initialized = false;
}
