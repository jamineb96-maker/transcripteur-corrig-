import { normalizePatients } from "./client/services/patients.js";

const TABS = ["pre_session", "post_session", "constellation", "anatomie3d", "facturation", "agenda"];
const SESSION_TAB_CONFIG = {
    pre_session: { kind: "pre", title: "Pré-séance" },
    post_session: { kind: "post", title: "Post-séance" },
};
const STORAGE_KEY = "ui:patient";
const FEATURE_FLAGS_URL = "./static/config/feature_flags.json";

let featureFlagsPromise;

async function getFeatureFlags() {
    if (!featureFlagsPromise) {
        featureFlagsPromise = fetchJSON(FEATURE_FLAGS_URL).catch(() => ({}));
    }
    return featureFlagsPromise;
}

const state = {
    patients: [],
    currentPatientId: null,
    currentTab: "pre_session",
    patientLibraryEmpty: false,
    showPatientsCta: false,
};

const banner = document.getElementById("banner");
const patientSelect = document.getElementById("patient-select");
const panel = document.getElementById("panel");
const tabsContainer = document.querySelector('[data-nav-list]');
const brandLink = document.querySelector('[data-nav-action="home"]');
const anatomyNavLink = document.querySelector('[data-nav-item="anatomie3d"]');
const patientControls = document.querySelector('.patient-controls');
const overflowContainer = document.querySelector('[data-nav-overflow]');
const overflowToggle = document.querySelector('[data-nav-toggle="overflow"]');
const overflowMenu = document.querySelector('[data-nav-menu]');

const overflowState = {
    expanded: false,
};

const API_BASE = typeof window !== "undefined" && typeof window.__API_BASE__ === "string"
    ? window.__API_BASE__
    : "";

function setOverflowExpanded(expanded) {
    overflowState.expanded = Boolean(expanded);
    const value = overflowState.expanded ? "true" : "false";
    if (overflowContainer) {
        overflowContainer.dataset.expanded = value;
    }
    if (overflowToggle) {
        overflowToggle.setAttribute("aria-expanded", value);
        overflowToggle.dataset.expanded = value;
    }
    if (overflowMenu) {
        overflowMenu.hidden = !overflowState.expanded;
        overflowMenu.classList.toggle("is-open", overflowState.expanded);
        overflowMenu.dataset.expanded = value;
    }
}

function closeOverflowMenu() {
    setOverflowExpanded(false);
}

function toggleOverflowMenu() {
    setOverflowExpanded(!overflowState.expanded);
}

function handleOverflowDocumentClick(event) {
    if (!overflowState.expanded) {
        return;
    }
    if (!overflowContainer) {
        return;
    }
    if (overflowContainer.contains(event.target)) {
        return;
    }
    closeOverflowMenu();
}

function handleOverflowKeydown(event) {
    if (!overflowState.expanded) {
        return;
    }
    if (event.key === "Escape" || event.key === "Esc") {
        event.preventDefault();
        closeOverflowMenu();
        if (overflowToggle) {
            overflowToggle.focus();
        }
    }
}

if (overflowToggle && overflowMenu) {
    overflowToggle.addEventListener("click", event => {
        event.preventDefault();
        if (overflowToggle.disabled) {
            return;
        }
        toggleOverflowMenu();
    });
}

document.addEventListener("click", handleOverflowDocumentClick, true);
document.addEventListener("keydown", handleOverflowKeydown, true);

setOverflowExpanded(false);

let anatomyEnabled = true;
let anatomyRoot = null;
let anatomyMarkup = null;
let anatomyModule = null;

getFeatureFlags().then(flags => {
    anatomyEnabled = flags?.anatomy3d_enabled !== false;
    if (!anatomyEnabled && anatomyNavLink) {
        const anchor = anatomyNavLink.closest("a");
        if (anchor) {
            anchor.setAttribute("hidden", "true");
            anchor.style.display = "none";
        }
    }
});

function navigate(target) {
    closeOverflowMenu();
    const destination = typeof target === "string" ? target : null;
    if (!destination || destination === "home") {
        window.location.hash = "#pre_session";
        return;
    }
    if (TABS.includes(destination)) {
        window.location.hash = `#${destination}`;
    }
}

window.navigate = navigate;

function capitalizeName(id) {
    return id
        .split(/[_\s]+/)
        .filter(Boolean)
        .map(part => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
}

function showBanner(message, type = "warning") {
    banner.classList.remove("visible", "warning", "info");
    if (!message) {
        banner.textContent = "";
        return;
    }
    banner.textContent = message;
    banner.classList.add("visible", type);
}

function renderPatientsCta() {
    if (!patientControls) {
        return;
    }
    const existing = patientControls.querySelector('[data-patients-cta]');
    const shouldShow = state.showPatientsCta && state.currentTab !== "anatomie3d";
    if (!shouldShow) {
        if (existing) {
            existing.remove();
        }
        return;
    }
    const message =
        'Aucun patient local détecté dans ce clone. Utilisez “Charger la démo” ou copiez vos données dans server/library/store/.';
    let cta = existing;
    if (!cta) {
        cta = document.createElement("p");
        cta.className = "patient-controls__cta";
        cta.dataset.patientsCta = "true";
        patientControls.appendChild(cta);
    }
    cta.textContent = message;
}

function renderPatientOptions(patients) {
    if (!patientSelect) {
        return;
    }
    patientSelect.innerHTML = "";
    const fragment = document.createDocumentFragment();
    patients.forEach(patient => {
        if (!patient || typeof patient !== "object") {
            return;
        }
        const option = document.createElement("option");
        option.value = patient.id;
        option.textContent = patient.displayName || capitalizeName(patient.id);
        if (patient.email) {
            option.dataset.email = patient.email;
        }
        fragment.appendChild(option);
    });
    patientSelect.appendChild(fragment);
    patientSelect.disabled = patients.length === 0;
}

function setActiveTab(tabId) {
    if (!tabsContainer) {
        return;
    }
    [...tabsContainer.querySelectorAll("a[data-tab]")].forEach(link => {
        if (link.dataset.tab === tabId) {
            link.classList.add("active");
        } else {
            link.classList.remove("active");
        }
    });
}

function renderPlaceholder(tabId) {
    const placeholders = {
        constellation: "Module Constellation à venir.",
        facturation: "Gestion de facturation disponible prochainement.",
        agenda: "Agenda en cours de construction.",
    };
    return `<p class="placeholder">${placeholders[tabId] || "Section en préparation."}</p>`;
}

async function fetchJSON(url) {
    const response = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.json();
}

async function fetchText(url) {
    const response = await fetch(url, {
        headers: { "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.1" },
    });
    if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.text();
}

function isLikelyArtifactPath(value) {
    if (typeof value !== "string") {
        return false;
    }
    const trimmed = value.trim();
    if (!trimmed || /\s/.test(trimmed)) {
        return false;
    }
    if (/^https?:/i.test(trimmed)) {
        return true;
    }
    return /[./]/.test(trimmed);
}

async function resolveSessionTextCandidate(candidate) {
    if (typeof candidate !== "string") {
        return null;
    }
    const trimmed = candidate.trim();
    if (!trimmed) {
        return null;
    }
    if (/^https?:/i.test(trimmed)) {
        return fetchText(trimmed);
    }
    if (isLikelyArtifactPath(trimmed) && !trimmed.includes("\n")) {
        const normalized = trimmed.replace(/^\/+/, "");
        try {
            return await fetchText(`${API_BASE}/artifacts/${normalized}`);
        } catch (error) {
            console.debug("[assist-cli] artifact fetch failed", normalized, error);
            return null;
        }
    }
    return trimmed;
}

async function resolveSessionContentFromCandidates(candidates) {
    for (const candidate of candidates) {
        try {
            const resolved = await resolveSessionTextCandidate(candidate);
            if (typeof resolved === "string" && resolved.trim()) {
                return resolved;
            }
        } catch (error) {
            console.debug("[assist-cli] candidate resolution failed", error);
        }
    }
    return null;
}

async function loadSession(tabId) {
    const config = SESSION_TAB_CONFIG[tabId] ?? SESSION_TAB_CONFIG.pre_session;
    const normalizedKind = config.kind;
    const patientId = state.currentPatientId;
    if (!patientId) {
        return "Sélectionnez un patient pour afficher les notes.";
    }
    const patient = state.patients.find(item => item.id === patientId) || null;
    const slug = (patient && (patient.slug || patient.id)) || patientId;
    if (!slug) {
        return "Patient sélectionné introuvable.";
    }

    const attempts = [];

    attempts.push(async () => {
        const url = `${API_BASE}/api/clinical/patient/${encodeURIComponent(slug)}/session/${encodeURIComponent(normalizedKind)}/materials`;
        const payload = await fetchJSON(url);
        const candidates = [
            payload?.mail_md,
            payload?.mail_markdown,
            payload?.mail,
            payload?.transcript,
            payload?.content,
            payload?.notes,
        ];
        return resolveSessionContentFromCandidates(candidates);
    });

    if (normalizedKind === "post") {
        attempts.push(async () => {
            const payload = await fetchJSON(`${API_BASE}/api/post/assets?patient=${encodeURIComponent(slug)}`);
            if (payload?.ok === false) {
                throw new Error(payload?.message || payload?.error || "post_assets_error");
            }
            const candidates = [
                payload?.mail_md,
                payload?.mail_markdown,
                payload?.mail,
                payload?.transcript,
                payload?.plan_text,
            ];
            return resolveSessionContentFromCandidates(candidates);
        });

        attempts.push(async () => {
            const transcript = await fetchText(
                `${API_BASE}/api/post/assets?patient=${encodeURIComponent(slug)}&kind=transcript`
            );
            return transcript && transcript.trim() ? transcript : null;
        });
    }

    attempts.push(async () => {
        const context = await fetchJSON(`${API_BASE}/api/post-session/context?patient=${encodeURIComponent(slug)}`);
        const candidates = [context?.last_notes, context?.notes, context?.summary];
        return resolveSessionContentFromCandidates(candidates);
    });

    let lastError = null;
    for (const attempt of attempts) {
        try {
            const result = await attempt();
            if (typeof result === "string" && result.trim()) {
                return result.trim();
            }
        } catch (error) {
            lastError = error;
        }
    }

    if (lastError) {
        throw lastError;
    }
    return "Aucun contenu disponible pour le moment.";
}

async function loadPatients() {
    state.patientLibraryEmpty = false;
    state.showPatientsCta = false;
    renderPatientsCta();
    try {
        const data = await fetchJSON("./api/patients");
        if (data && data.success === false) {
            const reason = typeof data.error === "string" ? data.error : "api_error";
            throw new Error(`API error: ${reason}`);
        }
        const patients = normalizePatients(data?.patients ?? data?.data);
        state.patients = patients;
        const roots = Array.isArray(data?.roots) ? data.roots : [];
        const dirAbs = typeof data?.dir_abs === "string" ? data.dir_abs.trim() : "";
        const libraryEmpty = roots.length === 0 && dirAbs === "";
        state.patientLibraryEmpty = libraryEmpty;
        state.showPatientsCta = libraryEmpty && patients.length === 0;
        renderPatientOptions(patients);
        const storedPatientId = localStorage.getItem(STORAGE_KEY);
        const selected = patients.find(patient => patient.id === storedPatientId)
            ? storedPatientId
            : patients[0]?.id ?? null;
        if (selected) {
            state.currentPatientId = selected;
            if (patientSelect) {
                patientSelect.value = selected;
            }
        } else {
            state.currentPatientId = null;
            if (patientSelect) {
                patientSelect.value = "";
            }
        }
        renderPatientsCta();
        showBanner("");
        return patients;
    } catch (error) {
        console.error("[assist-cli] patients load failed", error);
        state.patients = [];
        state.currentPatientId = null;
        state.patientLibraryEmpty = true;
        state.showPatientsCta = true;
        renderPatientOptions([]);
        renderPatientsCta();
        showBanner("Impossible de charger la liste des patients. Veuillez vérifier la connexion à l'API.", "warning");
        return [];
    }
}

async function updatePanel() {
    const tabId = state.currentTab;
    setActiveTab(tabId);
    renderPatientsCta();

    if (!state.currentPatientId && state.patients.length > 0) {
        state.currentPatientId = state.patients[0].id;
        patientSelect.value = state.currentPatientId;
    }

    if (SESSION_TAB_CONFIG[tabId]) {
        panel.innerHTML = "<p class=\"loading\">Chargement…</p>";
        try {
            const content = await loadSession(tabId);
            const title = SESSION_TAB_CONFIG[tabId]?.title ?? "Notes";
            panel.innerHTML = `<article class="notes"><h2>${title}</h2><pre>${escapeHtml(
                content
            )}</pre></article>`;
            showBanner("");
        } catch (error) {
            console.error("Erreur lors du chargement des notes", error);
            showBanner(
                "Certaines données n'ont pas pu être chargées. Veuillez vérifier la connexion à l'API.",
                "warning"
            );
            panel.innerHTML = "<p class=\"placeholder\">Aucun contenu disponible (erreur de chargement).</p>";
        }
    } else if (tabId === "anatomie3d") {
        await loadAnatomyTab();
    } else {
        panel.innerHTML = renderPlaceholder(tabId);
    }
}

async function loadAnatomyTab() {
    const flags = await getFeatureFlags();
    anatomyEnabled = flags?.anatomy3d_enabled !== false;
    if (!anatomyEnabled) {
        panel.innerHTML = "<p class=\"placeholder\">Module anatomie désactivé.</p>";
        return;
    }
    try {
        if (!anatomyMarkup) {
            const response = await fetch("/static/tabs/anatomy3d/index.html", { cache: "no-store" });
            anatomyMarkup = await response.text();
        }
        if (anatomyRoot) {
            panel.innerHTML = "";
            panel.appendChild(anatomyRoot);
            return;
        }
        panel.innerHTML = anatomyMarkup;
        anatomyRoot = panel.querySelector("[data-anatomy3d-root]");
        if (!anatomyRoot) {
            return;
        }
        if (!anatomyModule) {
            anatomyModule = await import("/static/tabs/anatomy3d/index.js");
        }
        await anatomyModule.initAnatomy3D(anatomyRoot, { flags });
    } catch (error) {
        console.error("[anatomy3d] Chargement anatomie", error);
        panel.innerHTML = "<p class=\"placeholder\">Impossible de charger l'onglet anatomie.</p>";
    }
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function handleHashChange() {
    closeOverflowMenu();
    const hash = window.location.hash.replace(/^#/, "");
    if (TABS.includes(hash)) {
        if (hash === "anatomie3d" && !anatomyEnabled) {
            window.location.hash = "#pre_session";
            return;
        }
        state.currentTab = hash;
    } else {
        state.currentTab = "pre_session";
        if (!hash || hash !== "pre_session") {
            window.location.hash = "#pre_session";
            return;
        }
    }
    updatePanel();
}

patientSelect.addEventListener("change", () => {
    state.currentPatientId = patientSelect.value;
    localStorage.setItem(STORAGE_KEY, state.currentPatientId);
    updatePanel();
});

if (brandLink) {
    brandLink.addEventListener("click", event => {
        event.preventDefault();
        navigate("home");
    });
}

window.addEventListener("hashchange", handleHashChange);

async function initializeApp() {
    try {
        const patients = await loadPatients();
        if (patients.length === 0) {
            panel.innerHTML = "<p class=\"placeholder\">Aucun patient disponible.</p>";
        }
    } catch (error) {
        console.error("Initialisation impossible", error);
        panel.innerHTML = "<p class=\"placeholder\">Erreur lors de l'initialisation de l'application.</p>";
    } finally {
        handleHashChange();
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeApp, { once: true });
} else {
    initializeApp();
}
