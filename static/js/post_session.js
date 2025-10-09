const $ = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));

const stepEls = $$('.stepper li');
const setStep = (n) => {
  stepEls.forEach((li, i) => li.classList.toggle('active', i <= n));
  ['import','transcript','analysis','research','mail'].forEach((k, i) => {
    $('#step-'+k).classList.toggle('hidden', i !== n);
  });
};

const toast = (msg, kind='ok') => {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 4200);
};

const prog = {
  el: $('#progress'),
  bar: $('#progress .bar'),
  txt: $('#progress .progress-text'),
  show(pct, label) {
    this.el.classList.remove('hidden');
    this.bar.style.width = `${pct}%`;
    if (label) this.txt.textContent = label;
  },
  hide() { this.el.classList.add('hidden'); this.bar.style.width = '0%'; }
};

async function health() {
  try {
    const r = await fetch('/_health');
    const j = await r.json();
    const el = $('#health-pill');
    if (j && j.ok) { el.textContent = 'Prêt'; el.className = 'pill pill-ok'; }
    else { el.textContent = 'Service dégradé'; el.className = 'pill pill-bad'; }
  } catch {
    const el = $('#health-pill');
    el.textContent = 'Hors-ligne'; el.className = 'pill pill-bad';
  }
}

async function doTranscribe() {
  const file = $('#fileInput').files[0];
  const raw = $('#rawText').value.trim();
  const prenom = $('#prenom').value.trim();
  const register = $('#register').value;

  if (!file && !raw) { toast("Fournir un audio ou coller un texte.", 'err'); return; }

  setStep(1);
  prog.show(8, 'Préparation…');

  let body;
  let headers = {};
  if (file) {
    const form = new FormData();
    form.append('audio', file);
    form.append('chunk_seconds', '120');
    form.append('overlap_seconds', '4');
    body = form;
  } else {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify({ transcript: raw });
  }

  try {
    prog.show(18, 'Transcription en cours…');
    const res = await fetch('/transcribe', { method: 'POST', body, headers });
    if (!res.ok) throw new Error('HTTP '+res.status);
    const j = await res.json();
    $('#transcript').value = j.transcript || '';
    toast(j.cached ? 'Transcription chargée depuis le cache.' : 'Transcription terminée.');
    prog.hide();
    setStep(1);
  } catch (e) {
    prog.hide();
    toast('Échec transcription : '+e.message, 'err');
    setStep(0);
    return;
  }
}

async function doAnalysis() {
  setStep(2);
  const transcript = $('#transcript').value;
  if (!transcript.trim()) { toast('Transcription vide.', 'err'); return; }
  try {
    const res = await fetch('/prepare_prompt?stage=research', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        transcript,
        prenom: $('#prenom').value.trim() || undefined,
        register: $('#register').value
      })
    });
    const j = await res.json();
    $('#analysisBox').textContent = JSON.stringify({
      lenses: j.lenses_used, chapters: j.chapters, points: j.points_mail
    }, null, 2);
    window.__research = j;
    toast('Analyse OK');
  } catch (e) {
    toast('Échec analyse : '+e.message, 'err');
  }
}

async function doResearch() {
  setStep(3);
  const r = window.__research;
  if (!r) { toast('Aucune analyse disponible.', 'err'); return; }
  $('#researchBox').textContent = JSON.stringify(r, null, 2);
  toast('Research prête.');
}

async function doFinal() {
  setStep(4);
  const r = window.__research;
  if (!r) { toast('Aucune research à transformer.', 'err'); return; }
  try {
    const res = await fetch('/prepare_prompt?stage=final', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(r)
    });
    const j = await res.json();
    const html = (j.mail_markdown || '')
      .replace(/^# (.*)$/gm,'<h1>$1</h1>')
      .replace(/^## (.*)$/gm,'<h2>$1</h2>')
      .replace(/\n\n/g, '</p><p>')
      .replace(/^\s*$/gm,'');
    $('#mailPreview').innerHTML = '<p>'+html+'</p>';
    toast('Mail généré.');
  } catch (e) {
    toast('Échec génération : '+e.message, 'err');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  health();
  setStep(0);
  $('#btnTranscribe').addEventListener('click', doTranscribe);
  $('#toAnalysis')?.addEventListener('click', doAnalysis);
  $('#toResearch')?.addEventListener('click', doResearch);
  $('#toFinal')?.addEventListener('click', doFinal);
  $('#backToImport')?.addEventListener('click', () => setStep(0));
});
