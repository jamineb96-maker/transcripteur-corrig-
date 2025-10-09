/*
 * Client‑side logic for the post‑session assistant.
 *
 * This script orchestrates a simple 5‑step wizard:
 *   1. Collect audio or transcript and basic metadata
 *   2. Transcribe audio (if provided) and display the transcript
 *   3. Produce the research payload and show evidence, critical notes etc.
 *   4. Produce the final plan and mail
 *   5. Persist the session and display links to artefacts
 */

(() => {
  // DOM references
  const step1 = document.getElementById('step1');
  const step2 = document.getElementById('step2');
  const step3 = document.getElementById('step3');
  const step4 = document.getElementById('step4');
  const step5 = document.getElementById('step5');
  const toast = document.getElementById('toast');
  const audioInput = document.getElementById('audioInput');
  const transcriptInput = document.getElementById('transcriptInput');
  const prenomInput = document.getElementById('prenomInput');
  const registerInput = document.getElementById('registerInput');
  const startBtn = document.getElementById('startBtn');
  const progressDiv = document.getElementById('progress');
  const transcriptOutput = document.getElementById('transcriptOutput');
  const toResearchBtn = document.getElementById('toResearchBtn');
  const researchOutput = document.getElementById('researchOutput');
  const toFinalBtn = document.getElementById('toFinalBtn');
  const finalPlan = document.getElementById('finalPlan');
  const finalMail = document.getElementById('finalMail');
  const saveSessionBtn = document.getElementById('saveSessionBtn');
  const artifactsList = document.getElementById('artifactsList');
  const restartBtn = document.getElementById('restartBtn');

  let transcriptText = '';
  let researchPayload = null;
  let finalPayload = null;

  function showToast(msg, duration = 3000) {
    toast.innerText = msg;
    toast.hidden = false;
    setTimeout(() => {
      toast.hidden = true;
    }, duration);
  }

  function showStep(step) {
    [step1, step2, step3, step4, step5].forEach((sec) => {
      sec.hidden = sec !== step;
    });
  }

  async function transcribeAudioOrText() {
    const prenom = prenomInput.value.trim();
    const register = registerInput.value.trim() || 'vous';
    const audioFile = audioInput.files[0];
    const rawText = transcriptInput.value.trim();
    progressDiv.innerText = 'Transcription en cours…';
    try {
      let response;
      if (audioFile) {
        const formData = new FormData();
        formData.append('audio', audioFile);
        formData.append('chunk_seconds', '120');
        formData.append('overlap_seconds', '4');
        // Forward metadata for idempotency
        response = await fetch('/transcribe', {
          method: 'POST',
          body: formData,
        });
      } else if (rawText) {
        response = await fetch('/transcribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ transcript: rawText }),
        });
      } else {
        showToast('Veuillez fournir un fichier audio ou un texte.');
        return;
      }
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        showToast(data.message || 'Erreur de transcription');
        return;
      }
      const data = await response.json();
      transcriptText = data.transcript || '';
      transcriptOutput.value = transcriptText;
      showStep(step2);
    } catch (error) {
      console.error(error);
      showToast('Erreur réseau lors de la transcription');
    }
  }

  async function runResearch() {
    progressDiv.innerText = 'Analyse en cours…';
    const prenom = prenomInput.value.trim();
    const register = registerInput.value.trim() || 'vous';
    try {
      const response = await fetch('/prepare_prompt?stage=research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: transcriptText, prenom, register }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        showToast(data.message || 'Erreur lors de l’analyse');
        return;
      }
      researchPayload = await response.json();
      researchOutput.textContent = JSON.stringify(researchPayload, null, 2);
      showStep(step3);
    } catch (error) {
      console.error(error);
      showToast('Erreur réseau lors de l’analyse');
    }
  }

  async function runFinal() {
    progressDiv.innerText = 'Synthèse en cours…';
    try {
      const response = await fetch('/prepare_prompt?stage=final', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(researchPayload || {}),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        showToast(data.message || 'Erreur lors de la synthèse');
        return;
      }
      finalPayload = await response.json();
      finalPlan.textContent = finalPayload.plan_markdown || '';
      finalMail.textContent = finalPayload.mail_markdown || '';
      showStep(step4);
    } catch (error) {
      console.error(error);
      showToast('Erreur réseau lors de la synthèse');
    }
  }

  async function saveSession() {
    const prenom = prenomInput.value.trim();
    const register = registerInput.value.trim() || 'vous';
    try {
      const response = await fetch('/post_session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: transcriptText, prenom, register }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        showToast(data.message || 'Erreur lors de l’enregistrement');
        return;
      }
      const data = await response.json();
      // Populate artefacts list
      artifactsList.innerHTML = '';
      const artifacts = data.artifacts || {};
      Object.keys(artifacts).forEach((key) => {
        const path = artifacts[key];
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = '/artifacts/' + path;
        a.innerText = key;
        a.target = '_blank';
        li.appendChild(a);
        artifactsList.appendChild(li);
      });
      showStep(step5);
    } catch (error) {
      console.error(error);
      showToast('Erreur réseau lors de l’enregistrement');
    }
  }

  // Event bindings
  startBtn.addEventListener('click', (evt) => {
    evt.preventDefault();
    showStep(step2);
    transcribeAudioOrText();
  });
  toResearchBtn.addEventListener('click', (evt) => {
    evt.preventDefault();
    runResearch();
  });
  toFinalBtn.addEventListener('click', (evt) => {
    evt.preventDefault();
    runFinal();
  });
  saveSessionBtn.addEventListener('click', (evt) => {
    evt.preventDefault();
    saveSession();
  });
  restartBtn.addEventListener('click', (evt) => {
    evt.preventDefault();
    // reset state
    transcriptText = '';
    researchPayload = null;
    finalPayload = null;
    transcriptOutput.value = '';
    researchOutput.textContent = '';
    finalPlan.textContent = '';
    finalMail.textContent = '';
    audioInput.value = '';
    transcriptInput.value = '';
    showStep(step1);
  });
})();