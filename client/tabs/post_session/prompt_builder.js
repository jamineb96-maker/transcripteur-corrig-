const STORAGE_KEY = 'postSession.promptBuilder.v1';
const DEFAULT_INCLUDE = {
  segments: true,
  milestones: true,
  quotes: true,
  contradictions: true,
  contexts: true,
  somatic: true,
  trauma_profile: true,
  unresolved_objectives: true,
};

const DEFAULT_STATE = {
  windowType: 'sessions',
  windowCount: 6,
  include: { ...DEFAULT_INCLUDE },
  topics: '',
  maxTokens: 1400,
  strictAttribution: true,
};

function safeParse(raw) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (error) {
    console.warn('[prompt-builder] unable to parse prefs', error);
    return null;
  }
}

function debounce(fn, delay = 240) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

export class PromptBuilder {
  constructor(options = {}) {
    this.options = {
      getPatient: () => '',
      onToast: () => {},
      onCopy: () => {},
      ...options,
    };
    this.state = this._loadState();
    this.root = null;
    this.preview = null;
    this.tokenCount = null;
    this.riskCount = null;
    this.copyButton = null;
    this.topicsInput = null;
    this.windowSelect = null;
    this.windowCount = null;
    this.toggleStrict = null;
    this.maxTokensInput = null;
    this.checkboxes = new Map();
    this.lastResult = null;
    this.textarea = null;
    this.busy = false;
    this.saveLater = debounce(() => this._persistState());
  }

  mount(card, textarea) {
    if (this.root && !document.body.contains(this.root)) {
      this.root = null;
    }
    if (!card || this.root) {
      this.textarea = textarea || this.textarea;
      return;
    }
    this.textarea = textarea || null;
    this.root = document.createElement('div');
    this.root.className = 'ps-prompt-builder';
    this.root.innerHTML = this._template();
    const header = card.querySelector('h2');
    if (header && header.nextSibling) {
      card.insertBefore(this.root, header.nextSibling);
    } else {
      card.appendChild(this.root);
    }
    this._mapElements();
    this._restoreState();
    this._bindEvents();
    this._renderPreview('Aucune donnée prévisualisée.');
    this._updateTokenCount(0);
    this._updateRiskCount(0);
  }

  reset() {
    this.lastResult = null;
    if (this.textarea) {
      this.textarea.value = '';
    }
    this._renderPreview('Aucune donnée prévisualisée.');
    this._updateTokenCount(0);
    this._updateRiskCount(0);
  }

  onPatientChanged() {
    this.reset();
  }

  _template() {
    return `
      <div class="pb-pane">
        <div class="pb-row">
          <label for="pb-window">Fenêtre</label>
          <select id="pb-window">
            <option value="sessions">6 dernières séances</option>
            <option value="months">Période en mois</option>
          </select>
          <input id="pb-window-count" type="number" min="1" max="12" step="1" />
        </div>
        <div class="pb-row pb-topics">
          <label for="pb-topics">Topics (optionnel)</label>
          <input id="pb-topics" type="text" placeholder="fatigue cognitive, culpabilité…" />
        </div>
        <fieldset class="pb-include">
          <legend>Sections à inclure</legend>
          <div class="pb-grid"></div>
        </fieldset>
        <div class="pb-row pb-meta">
          <label for="pb-max-tokens">Max tokens</label>
          <input id="pb-max-tokens" type="number" min="400" max="3200" step="50" />
          <label class="pb-strict">
            <input id="pb-strict" type="checkbox" checked /> Attribution stricte (recommandé)
          </label>
        </div>
        <div class="pb-actions">
          <button id="pb-preview" class="btn secondary" type="button">Prévisualiser</button>
          <button id="pb-copy" class="btn ghost" type="button">Copier</button>
          <span class="pb-tokens" data-token-count>0 tokens</span>
          <span class="pb-risk" data-risk-count>0 occurrence de “vous avez” non justifiée</span>
        </div>
        <div class="pb-preview" data-preview></div>
      </div>
    `;
  }

  _mapElements() {
    if (!this.root) return;
    this.preview = this.root.querySelector('[data-preview]');
    this.tokenCount = this.root.querySelector('[data-token-count]');
    this.riskCount = this.root.querySelector('[data-risk-count]');
    this.copyButton = this.root.querySelector('#pb-copy');
    this.topicsInput = this.root.querySelector('#pb-topics');
    this.windowSelect = this.root.querySelector('#pb-window');
    this.windowCount = this.root.querySelector('#pb-window-count');
    this.maxTokensInput = this.root.querySelector('#pb-max-tokens');
    this.toggleStrict = this.root.querySelector('#pb-strict');
    const includeContainer = this.root.querySelector('.pb-grid');
    if (includeContainer && !includeContainer.children.length) {
      Object.entries(DEFAULT_INCLUDE).forEach(([key]) => {
        const id = `pb-include-${key}`;
        const wrapper = document.createElement('label');
        wrapper.className = 'pb-checkbox';
        wrapper.innerHTML = `
          <input type="checkbox" id="${id}" data-section="${key}" />
          <span>${this._labelForSection(key)}</span>
        `;
        includeContainer.appendChild(wrapper);
        this.checkboxes.set(key, wrapper.querySelector('input'));
      });
    }
  }

  _restoreState() {
    const state = this.state;
    if (this.windowSelect) this.windowSelect.value = state.windowType || 'sessions';
    if (this.windowCount) this.windowCount.value = state.windowCount || 6;
    if (this.topicsInput) this.topicsInput.value = state.topics || '';
    if (this.maxTokensInput) this.maxTokensInput.value = state.maxTokens || 1400;
    if (this.toggleStrict) this.toggleStrict.checked = state.strictAttribution !== false;
    this.checkboxes.forEach((input, key) => {
      const includeState = state.include?.[key];
      input.checked = includeState !== false;
    });
  }

  _bindEvents() {
    if (!this.root) return;
    const previewBtn = this.root.querySelector('#pb-preview');
    if (previewBtn) {
      previewBtn.addEventListener('click', () => this.compose());
    }
    if (this.copyButton) {
      this.copyButton.addEventListener('click', () => {
        if (this.lastResult?.prompt) {
          this.options.onCopy(this.lastResult.prompt);
        } else if (this.textarea?.value) {
          this.options.onCopy(this.textarea.value);
        } else {
          this.options.onToast('Aucun prompt à copier.', 'warn');
        }
      });
    }
    if (this.topicsInput) {
      this.topicsInput.addEventListener('input', () => {
        this.state.topics = this.topicsInput.value;
        this.saveLater();
      });
    }
    if (this.windowSelect) {
      this.windowSelect.addEventListener('change', () => {
        this.state.windowType = this.windowSelect.value;
        this.saveLater();
      });
    }
    if (this.windowCount) {
      this.windowCount.addEventListener('input', () => {
        const value = Number(this.windowCount.value) || 6;
        this.state.windowCount = Math.max(1, value);
        this.saveLater();
      });
    }
    if (this.maxTokensInput) {
      this.maxTokensInput.addEventListener('input', () => {
        const value = Number(this.maxTokensInput.value) || 1400;
        this.state.maxTokens = Math.max(400, value);
        this.saveLater();
      });
    }
    if (this.toggleStrict) {
      this.toggleStrict.addEventListener('change', () => {
        this.state.strictAttribution = this.toggleStrict.checked;
        this.saveLater();
      });
    }
    this.checkboxes.forEach((input, key) => {
      input.addEventListener('change', () => {
        this.state.include[key] = input.checked;
        this.saveLater();
      });
    });
  }

  async compose() {
    if (this.busy) return;
    const patient = this.options.getPatient();
    if (!patient) {
      this.options.onToast('Sélectionnez un·e patient·e avant de composer.', 'warn');
      return;
    }
    const payload = this._buildPayload(patient);
    if (!payload) {
      this.options.onToast('Configuration invalide pour la composition.', 'error');
      return;
    }
    await this._fetchPrompt(payload);
  }

  _buildPayload(slug) {
    const windowCount = Math.max(1, Number(this.state.windowCount) || 6);
    const maxTokens = Math.max(400, Number(this.state.maxTokens) || 1400);
    const include = {};
    Object.entries(this.state.include || {}).forEach(([key, value]) => {
      include[key] = Boolean(value);
    });
    const topics = (this.state.topics || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
    return {
      slug,
      window: { type: this.state.windowType || 'sessions', count: windowCount },
      topics,
      include,
      max_tokens: maxTokens,
      attribution_strict: this.state.strictAttribution !== false,
    };
  }

  async _fetchPrompt(payload) {
    this._setBusy(true);
    try {
      // Obsolète — le prompt final est désormais injecté par /api/post/v2/megaprompt via index.js.
      // const response = await fetch('/api/postsession/prompt/compose', {
      //   method: 'POST',
      //   headers: { 'Content-Type': 'application/json' },
      //   body: JSON.stringify(payload),
      // });
      const prompt = this.textarea?.value || '';
      const result = { prompt, trace: null, usage: { meta: prompt.length } };
      this.lastResult = result;
      this._applyResult(result);
      this.options.onToast('Prompt post-séance prêt.', 'success');
    } catch (error) {
      console.error('[prompt-builder] compose failed', error);
      this.options.onToast(error.message || 'Impossible de composer le prompt.', 'error');
    } finally {
      this._setBusy(false);
    }
  }

  _applyResult(result) {
    if (this.textarea) {
      this.textarea.value = result.prompt;
      const event = new Event('input', { bubbles: true });
      this.textarea.dispatchEvent(event);
    }
    this._renderPreview(result.prompt, result.trace);
    const usage = result.usage || {};
    this._updateTokenCount(usage.meta || 0);
    this._updateRiskCount(this._countRisks(result.prompt));
  }

  _renderPreview(prompt, trace = []) {
    if (!this.preview) return;
    if (!prompt) {
      this.preview.innerHTML = '<p class="pb-empty">Aucune donnée disponible.</p>';
      return;
    }
    const lines = prompt.split('\n');
    const html = lines
      .map((line) => {
        const trimmed = line.trim();
        if (!trimmed) {
          return '<div class="pb-line pb-empty">&nbsp;</div>';
        }
        let classes = 'pb-line';
        if (trimmed.startsWith('- [P-')) {
          classes += ' pb-patient';
        } else if (trimmed.startsWith('- [CL-') || trimmed.startsWith('Je note') || trimmed.startsWith('Hypothèse prudente')) {
          classes += ' pb-clinician';
        }
        return `<div class="${classes}">${this._escape(trimmed)}</div>`;
      })
      .join('');
    this.preview.innerHTML = html;
  }

  _labelForSection(key) {
    switch (key) {
      case 'segments':
        return 'Segments';
      case 'milestones':
        return 'Repères';
      case 'quotes':
        return 'Citations';
      case 'contradictions':
        return 'Contradictions';
      case 'contexts':
        return 'Contextes';
      case 'somatic':
        return 'Mémoire somatique';
      case 'trauma_profile':
        return 'Profil traumatique';
      case 'unresolved_objectives':
        return 'Objectifs ouverts';
      default:
        return key;
    }
  }

  _updateTokenCount(value) {
    if (this.tokenCount) {
      this.tokenCount.textContent = `${value || 0} tokens estimés`;
    }
  }

  _updateRiskCount(value) {
    if (this.riskCount) {
      this.riskCount.textContent = `${value} occurrence${value > 1 ? 's' : ''} de “vous avez” non justifiée`;
      this.riskCount.dataset.tone = value > 0 ? 'alert' : 'ok';
    }
  }

  _countRisks(prompt) {
    if (!prompt) return 0;
    const lines = prompt.split('\n');
    const pattern = /\b(vous avez|tu as|you said)\b/gi;
    let count = 0;
    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed) return;
      const matches = trimmed.match(pattern);
      if (!matches) return;
      if (trimmed.includes('[P-QUOTE]')) return;
      count += matches.length;
    });
    return count;
  }

  _setBusy(isBusy) {
    this.busy = isBusy;
    const previewBtn = this.root?.querySelector('#pb-preview');
    if (previewBtn) {
      previewBtn.disabled = isBusy;
      previewBtn.dataset.busy = isBusy ? 'true' : 'false';
      previewBtn.textContent = isBusy ? 'Chargement…' : 'Prévisualiser';
    }
  }

  _escape(value) {
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
  }

  _loadState() {
    const stored = safeParse(localStorage.getItem(STORAGE_KEY));
    if (!stored) {
      return JSON.parse(JSON.stringify(DEFAULT_STATE));
    }
    return {
      ...DEFAULT_STATE,
      ...stored,
      include: { ...DEFAULT_INCLUDE, ...(stored.include || {}) },
    };
  }

  _persistState() {
    const payload = {
      windowType: this.state.windowType,
      windowCount: this.state.windowCount,
      topics: this.state.topics,
      include: this.state.include,
      maxTokens: this.state.maxTokens,
      strictAttribution: this.state.strictAttribution,
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    } catch (error) {
      console.warn('[prompt-builder] unable to persist state', error);
    }
  }
}

