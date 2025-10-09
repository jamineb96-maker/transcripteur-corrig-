const TABS = ["pre", "post", "constellation", "anatomie", "facturation", "agenda"];
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
    currentTab: "pre",
    patientLibraryEmpty: false,
    showPatientsCta: false,
};

const banner = document.getElementById("banner");
const patientSelect = document.getElementById("patient-select");
const panel = document.getElementById("panel");
const tabsContainer = document.querySelector('[data-nav-list]');
const brandLink = document.querySelector('[data-nav-action="home"]');
const anatomyNavLink = document.querySelector('[data-nav-item="anatomie"]');
const patientControls = document.querySelector('.patient-controls');
const overflowContainer = document.querySelector('[data-nav-overflow]');
const overflowToggle = document.querySelector('[data-nav-toggle="overflow"]');
const overflowMenu = document.querySelector('[data-nav-menu]');

const overflowState = {
    expanded: false,
};

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
        window.location.hash = "#pre";
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
    const shouldShow = state.showPatientsCta && state.currentTab !== "anatomie";
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
        renderPatientsCta();
        showBanner("");
    } catch (error) {
@@ -162,67 +188,105 @@ async function loadSession(kind) {
        console.error(`Erreur lors du chargement ${kind}`, error);
        showBanner(
            "Certaines données n'ont pas pu être chargées. Veuillez vérifier la connexion à l'API.",
            "warning"
        );
        return "Aucun contenu disponible (erreur de chargement).";
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

    if (tabId === "pre" || tabId === "post") {
        panel.innerHTML = "<p class=\"loading\">Chargement…</p>";
        const content = await loadSession(tabId === "pre" ? "pre" : "post");
        const title = tabId === "pre" ? "Pré-séance" : "Post-séance";
        panel.innerHTML = `<article class="notes"><h2>${title}</h2><pre>${escapeHtml(
            content
        )}</pre></article>`;
    } else if (tabId === "anatomie") {
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
        if (hash === "anatomie" && !anatomyEnabled) {
            window.location.hash = "#pre";
            return;
        }
        state.currentTab = hash;
    } else {
        state.currentTab = "pre";
        if (!hash) {
            window.location.hash = "#pre";
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
