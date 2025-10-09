import { nanoid } from "./utils.js";

export function createSequenceEditor({ store, container, onPlaySnapshot, downloadFile }) {
  const dialog = document.createElement("dialog");
  dialog.className = "anatomy3d__dialog";
  dialog.innerHTML = `
    <article>
      <header>
        <h3>Composer un parcours</h3>
      </header>
      <div class="dialog-content">
        <form data-sequence-form>
          <label>Nom du parcours
            <input type="text" name="title" required placeholder="Ex: Parcours Douleur" />
          </label>
          <label>Objectifs (séparés par des virgules)
            <input type="text" name="objectives" placeholder="Ex: Modulation, Education" />
          </label>
          <div data-sequence-steps class="sequence-steps"></div>
          <button type="button" class="button secondary" data-action="add-step">Ajouter une étape</button>
        </form>
      </div>
      <footer>
        <button type="button" class="button secondary" data-action="import-sequence">Importer</button>
        <button type="button" class="button" data-action="save-sequence">Enregistrer</button>
        <button type="button" class="ghost" data-action="close-dialog">Fermer</button>
      </footer>
    </article>`;

  container.appendChild(dialog);

  const sequenceList = container.querySelector("[data-sequence-list]");
  const form = dialog.querySelector("[data-sequence-form]");
  const stepsContainer = dialog.querySelector("[data-sequence-steps]");
  const addStepBtn = dialog.querySelector('[data-action="add-step"]');
  const closeBtn = dialog.querySelector('[data-action="close-dialog"]');
  const saveBtn = dialog.querySelector('[data-action="save-sequence"]');
  const importBtn = dialog.querySelector('[data-action="import-sequence"]');

  function renderSequences() {
    sequenceList.innerHTML = "";
    store.state.sequences.forEach(seq => {
      const item = document.createElement("li");
      item.className = "sequence-item";
      item.innerHTML = `
        <span>
          <strong>${seq.title}</strong><br>
          <small>${seq.objectives?.join(", ") || "Sans objectifs"}</small>
        </span>
        <span>
          <button type="button" class="button secondary" data-sequence="${seq.id}" data-action="play">Lire</button>
          <button type="button" class="ghost" data-sequence="${seq.id}" data-action="export">Exporter</button>
        </span>`;
      sequenceList.appendChild(item);
    });
  }

  function addStepRow(step = {}) {
    const row = document.createElement("div");
    row.className = "sequence-step";
    row.innerHTML = `
      <label>ID snapshot
        <input type="text" name="snapshot" value="${step.snapshot_id || ""}" placeholder="Identifiant snapshot" required />
      </label>
      <label>Narration
        <textarea name="narration" rows="2" placeholder="Narration markdown">${step.narration || ""}</textarea>
      </label>
      <label>Pause (ms)
        <input type="number" name="pause" min="0" step="100" value="${step.pause_ms ?? 0}" />
      </label>
      <button type="button" class="ghost" data-action="remove-step">Supprimer</button>`;
    stepsContainer.appendChild(row);
  }

  function collectSteps() {
    return [...stepsContainer.querySelectorAll(".sequence-step")].map(row => ({
      snapshot_id: row.querySelector('input[name="snapshot"]').value.trim(),
      narration: row.querySelector('textarea[name="narration"]').value.trim(),
      pause_ms: Number(row.querySelector('input[name="pause"]').value) || 0,
    })).filter(step => step.snapshot_id);
  }

  function resetForm() {
    form.reset();
    stepsContainer.innerHTML = "";
    addStepRow();
  }

  addStepBtn.addEventListener("click", () => addStepRow());
  closeBtn.addEventListener("click", () => dialog.close());

  saveBtn.addEventListener("click", () => {
    const title = form.elements.title.value.trim();
    if (!title) {
      form.elements.title.focus();
      return;
    }
    const objectives = form.elements.objectives.value
      .split(",")
      .map(entry => entry.trim())
      .filter(Boolean);
    const steps = collectSteps();
    if (steps.length === 0) {
      addStepRow();
      return;
    }
    const sequence = {
      id: nanoid("sequence"),
      title,
      objectives,
      steps,
    };
    store.setSequences([...store.state.sequences, sequence]);
    renderSequences();
    dialog.close();
  });

  stepsContainer.addEventListener("click", event => {
    if (event.target.matches('[data-action="remove-step"]')) {
      event.target.closest(".sequence-step").remove();
    }
  });

  importBtn.addEventListener("click", () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "application/json";
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      if (!file) {
        return;
      }
      const text = await file.text();
      try {
        const data = JSON.parse(text);
        if (data && data.steps) {
          store.setSequences([...store.state.sequences, data]);
          renderSequences();
        }
      } catch (error) {
        console.error("Import sequence", error);
      }
    });
    input.click();
  });

  sequenceList.addEventListener("click", event => {
    const action = event.target.dataset.action;
    const id = event.target.dataset.sequence;
    const sequence = store.state.sequences.find(seq => seq.id === id);
    if (!sequence) {
      return;
    }
    if (action === "export") {
      downloadFile(JSON.stringify(sequence, null, 2), `${sequence.id}.json`, "application/json");
    }
    if (action === "play") {
      playSequence(sequence);
    }
  });

  function playSequence(sequence) {
    if (!sequence.steps?.length) {
      return;
    }
    let index = 0;
    function runStep() {
      const step = sequence.steps[index];
      if (!step) {
        return;
      }
      onPlaySnapshot(step);
      index += 1;
      if (index < sequence.steps.length) {
        setTimeout(runStep, Math.max(0, step.pause_ms || 0));
      }
    }
    runStep();
  }

  function open() {
    resetForm();
    dialog.showModal();
  }

  resetForm();
  renderSequences();

  return {
    open,
    render: renderSequences,
  };
}
