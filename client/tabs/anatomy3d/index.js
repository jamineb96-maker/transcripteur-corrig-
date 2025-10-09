import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

import { createStateStore } from "./state.js";
import { createSceneLoader } from "./scene_loader.js";
import { createSequenceEditor } from "./sequence_editor.js";
import { nanoid, downloadFile, debounce, clamp, lerp } from "./utils.js";

const TAB_ID = "anatomie3d";
const LOG_PREFIX = "[anatomy3d]";
const MODEL_URL = "/static/models/neurology.glb";
const STYLE_HREF = "/static/tabs/anatomy3d/style.css";
const CONFIG_BASE = "/static/tabs/anatomy3d";
const FEATURE_FLAGS_URL = "/static/config/feature_flags.json";
const JSPDF_URL = "/static/vendor/jspdf/jspdf.umd.min.js";
const THREE_VERSION = "0.159.0";
const THREE_VENDOR_BASE = "/static/vendor/three/";
const THREE_CDN_BASE = `https://unpkg.com/three@${THREE_VERSION}/`;
const USE_THREE_CDN = typeof window !== "undefined" && window.__THREE_IMPORT_MAP_CDN__ === true;
const DRACO_DECODER_PATH = `${USE_THREE_CDN ? THREE_CDN_BASE : THREE_VENDOR_BASE}examples/jsm/libs/draco/`;
const DRACO_WASM_URL = `${DRACO_DECODER_PATH}draco_decoder.wasm`;

if (USE_THREE_CDN) {
  console.warn(LOG_PREFIX, "Utilisation du CDN Three.js – vendors locaux indisponibles.");
}
const FALLBACK_IMAGE_URL = "/static/tabs/anatomy3d/fallback/overview.png";
const LICENSE_URL = "/static/models/neurology.license.md";
const SELFTEST_URL = "/static/tabs/anatomy3d/selftest.html";
const RETRY_LABEL = "Réessayer";
const RETRY_PENDING_LABEL = "Nouvelle tentative…";

let initialized = false;

function ensureStyles() {
  if (document.querySelector(`link[data-anatomy3d-style]`)) {
    return;
  }
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = STYLE_HREF;
  link.dataset.anatomy3dStyle = "true";
  document.head.appendChild(link);
}

async function fetchJSON(url, fallback = null) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.json();
  } catch (error) {
    console.warn(LOG_PREFIX, "unable to fetch", url, error);
    return fallback;
  }
}

async function assetExists(url) {
  try {
    const response = await fetch(url, { method: "HEAD" });
    if (!response.ok) {
      console.warn(LOG_PREFIX, `asset missing (${response.status})`, url);
      return false;
    }
    return true;
  } catch (error) {
    console.warn(LOG_PREFIX, "asset check failed", url, error);
    return false;
  }
}

function dispatchRetry() {
  if (typeof window.requestTabReload === "function") {
    window.requestTabReload(TAB_ID);
    return;
  }
  if (typeof window.retryTab === "function") {
    window.retryTab(TAB_ID);
    return;
  }
  window.dispatchEvent(
    new CustomEvent("assist:retry-tab", {
      detail: { tabId: TAB_ID },
    })
  );
}

function supportsWebGL() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl") || canvas.getContext("webgl2"));
  } catch (error) {
    return false;
  }
}

function ensureRetryButton(host) {
  if (!host) {
    return null;
  }
  let button = host.querySelector('[data-action="retry-tab"]');
  if (!button) {
    button = document.createElement("button");
    button.type = "button";
    button.className = "button primary";
    button.dataset.action = "retry-tab";
    button.dataset.tabId = TAB_ID;
    host.appendChild(button);
  }
  button.disabled = false;
  button.textContent = RETRY_LABEL;
  if (button.__retryHandler) {
    button.removeEventListener("click", button.__retryHandler);
  }
  const handler = () => {
    button.disabled = true;
    button.textContent = RETRY_PENDING_LABEL;
    dispatchRetry();
    button.__retryHandler = null;
  };
  button.__retryHandler = handler;
  button.addEventListener("click", handler, { once: true });
  return button;
}

function createRenderer(canvas, lowPower) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !lowPower, preserveDrawingBuffer: true });
  renderer.setPixelRatio(lowPower ? Math.min(window.devicePixelRatio, 1.5) : window.devicePixelRatio);
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
  renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.shadowMap.enabled = !lowPower;
  return renderer;
}

function createScene(lowPower) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x05070d);

  const ambient = new THREE.AmbientLight(0xffffff, lowPower ? 0.4 : 0.6);
  scene.add(ambient);

  const key = new THREE.DirectionalLight(0xffffff, lowPower ? 0.7 : 1.1);
  key.position.set(4, 6, 4);
  key.castShadow = !lowPower;
  scene.add(key);

  const rim = new THREE.DirectionalLight(0x88c9ff, lowPower ? 0.2 : 0.35);
  rim.position.set(-5, 4, -3);
  scene.add(rim);

  return scene;
}

function normalizeText(value) {
  return value
    .toLocaleLowerCase("fr")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "");
}

function prepareNodeIndex(root) {
  const map = new Map();
  root.traverse(child => {
    if (child.isMesh || child.isGroup) {
      map.set(child.name, child);
    }
  });
  return map;
}

function createRaycaster(camera) {
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  return {
    cast(event, intersectsRoot) {
      const rect = event.target.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const intersects = raycaster.intersectObjects(intersectsRoot, true);
      return intersects?.[0] || null;
    },
  };
}

async function loadSequences() {
  const manifest = await fetchJSON(`${CONFIG_BASE}/sequences_manifest.json`, []);
  const sequences = [];
  for (const file of manifest) {
    const data = await fetchJSON(`${CONFIG_BASE}/sequences/${file}`, null);
    if (data) {
      sequences.push(data);
    }
  }
  return sequences;
}

async function prepareFallbackElement(fallbackElement) {
  if (!fallbackElement) {
    return { element: null, message: null, hasImage: false };
  }
  const message = fallbackElement.querySelector("[data-fallback-message]") || null;
  const image = fallbackElement.querySelector("[data-fallback-image]") || null;
  if (!image) {
    return { element: fallbackElement, message, hasImage: false };
  }
  const exists = await assetExists(FALLBACK_IMAGE_URL);
  if (!exists) {
    fallbackElement.remove();
    return { element: null, message: null, hasImage: false };
  }
  image.src = FALLBACK_IMAGE_URL;
  image.hidden = false;
  return { element: fallbackElement, message, hasImage: true };
}

async function configureDracoLoader(loader) {
  try {
    const response = await fetch(DRACO_WASM_URL, { method: "HEAD" });
    if (response?.ok) {
      const draco = new DRACOLoader();
      draco.setDecoderPath(DRACO_DECODER_PATH);
      draco.setDecoderConfig?.({ type: "wasm" });
      loader.setDRACOLoader(draco);
      return true;
    }
    if (response) {
      console.warn(
        LOG_PREFIX,
        `Draco decoder unavailable (status ${response.status}) – continuing without Draco`
      );
    }
  } catch (error) {
    console.warn(LOG_PREFIX, "Draco decoder check failed – continuing without Draco", error);
  }
  if (USE_THREE_CDN) {
    console.warn(LOG_PREFIX, "CDN Three.js actif mais le décodeur Draco reste indisponible.");
  }
  return false;
}

function updateRibbon(element, mode) {
  element.textContent = mode === "linked" ? "Mode lié" : "Mode global";
  element.dataset.mode = mode;
}

function updateNotes({ scene, notesContainer, questionsContainer, mythsContainer }) {
  const safe = value => (Array.isArray(value) ? value : []);
  const notes = safe(scene.notes);
  const myths = safe(scene.myths);
  const questions = safe(scene.questions);

  notesContainer.innerHTML = notes
    .map(note => `<article><h4>${note.title}</h4><div>${renderMarkdown(note.text)}</div></article>`) 
    .join("") || `<p class="muted">Aucune note pour cette scène.</p>`;

  questionsContainer.innerHTML = questions.length
    ? `<h4>Questions</h4><ul>${questions.map(question => `<li>${question}</li>`).join("")}</ul>`
    : `<p class="muted">Pas de questions suggérées.</p>`;

  mythsContainer.innerHTML = myths.length
    ? `<h4>Neuromythes</h4><ul>${myths
        .map(myth => `<li><strong>${myth.claim}</strong><br><span>${myth.correction}</span></li>`)
        .join("")}</ul>`
    : `<p class="muted">Aucun mythe renseigné.</p>`;
}

function renderMarkdown(text = "") {
  return text
    .split(/\n{2,}/)
    .map(paragraph => {
      const listMatch = paragraph.trim().match(/^[-*] /m);
      if (listMatch) {
        return `<ul>${paragraph
          .split(/\n/)
          .map(line => line.replace(/^[-*]\s*/, ""))
          .map(line => `<li>${line}</li>`)
          .join("")}</ul>`;
      }
      return `<p>${paragraph.replace(/\n/g, "<br>")}</p>`;
    })
    .join("");
}

function getCameraTarget(controls) {
  return controls.target.clone();
}

function setCameraFromConfig({ camera, controls }, config) {
  const { position = [0, 1.5, 3], target = [0, 1, 0], fov = 40 } = config || {};
  camera.position.set(...position);
  controls.target.set(...target);
  camera.fov = fov;
  camera.updateProjectionMatrix();
  controls.update();
}

function extractVisibility(nodeMap) {
  const visibility = [];
  const opacity = [];
  nodeMap.forEach(node => {
    if (typeof node.visible === "boolean") {
      visibility.push({ node: node.name, visible: node.visible });
    }
    if (node.material && typeof node.material.opacity === "number") {
      opacity.push({ node: node.name, alpha: node.material.opacity });
    }
  });
  return { visibility, opacity };
}

function applyNodeVisibility(nodeMap, list) {
  list.forEach(entry => {
    const node = nodeMap.get(entry.node);
    if (node) {
      node.visible = entry.visible;
    }
  });
}

function applyNodeOpacity(nodeMap, list) {
  list.forEach(entry => {
    const node = nodeMap.get(entry.node);
    if (node && node.material) {
      node.material.transparent = entry.alpha < 1;
      node.material.opacity = clamp(entry.alpha, 0, 1);
      node.material.needsUpdate = true;
    }
  });
}

function applyLayerVisibility(nodeMap, group, visible) {
  group.nodes.forEach(name => {
    const node = nodeMap.get(name);
    if (node) {
      node.visible = visible;
    }
  });
}

function soloLayer(nodeMap, targetGroup, groups) {
  groups.forEach(group => {
    const visible = group.id === targetGroup.id;
    applyLayerVisibility(nodeMap, group, visible);
  });
}

function ghostLayers(nodeMap, targetGroup, groups, alpha = 0.2) {
  groups.forEach(group => {
    group.nodes.forEach(name => {
      const node = nodeMap.get(name);
      if (!node || !node.material) {
        return;
      }
      if (group.id === targetGroup.id) {
        node.material.transparent = false;
        node.material.opacity = 1;
      } else {
        node.material.transparent = true;
        node.material.opacity = alpha;
      }
      node.material.needsUpdate = true;
    });
  });
}

function highlightNode(node, duration = 1200) {
  if (!node || !node.material) {
    return;
  }
  const original = {
    emissive: node.material.emissive ? node.material.emissive.clone() : null,
    opacity: node.material.opacity,
    transparent: node.material.transparent,
  };
  node.material.transparent = false;
  node.material.emissive = new THREE.Color(0xffaa33);
  node.material.opacity = 1;
  node.material.needsUpdate = true;
  setTimeout(() => {
    if (!node.material) {
      return;
    }
    if (original.emissive) {
      node.material.emissive.copy(original.emissive);
    }
    node.material.transparent = original.transparent;
    node.material.opacity = original.opacity;
    node.material.needsUpdate = true;
  }, duration);
}

function updateGlossary(glossaryContainer, entry) {
  if (!entry) {
    glossaryContainer.innerHTML = `<p class="muted">Sélectionnez une structure pour afficher la définition.</p>`;
    return;
  }
  glossaryContainer.innerHTML = `
    <article class="glossary-entry">
      <h4>${entry.label_fr}</h4>
      <p>${entry.definition}</p>
      <p class="muted">Idée reçue : ${entry.misunderstanding}</p>
      ${Array.isArray(entry.links) && entry.links.length
        ? `<ul>${entry.links
            .map(link => `<li><a href="${link.href}" target="_blank" rel="noopener" data-glossary-link>${link.label}</a></li>`)
            .join("")}</ul>`
        : ""}
    </article>`;
}

function attachLinkHandlers(container) {
  container.addEventListener("click", event => {
    const anchor = event.target.closest("a[data-glossary-link]");
    if (!anchor) {
      return;
    }
    event.preventDefault();
    const panel = document.createElement("dialog");
    panel.className = "anatomy3d__dialog";
    panel.innerHTML = `<article><header><h3>${anchor.textContent}</h3></header><div class="dialog-content"><iframe src="${anchor.href}" title="${anchor.textContent}"></iframe></div><footer><button type="button" class="button" data-action="close-dialog">Fermer</button></footer></article>`;
    container.appendChild(panel);
    const close = panel.querySelector('[data-action="close-dialog"]');
    close.addEventListener("click", () => {
      panel.close();
      panel.remove();
    });
    panel.showModal();
  });
}

async function loadCredits(dialog, contentContainer) {
  const licenseText = await fetch(LICENSE_URL)
    .then(resp => (resp.ok ? resp.text() : null))
    .catch(error => {
      console.warn(LOG_PREFIX, "unable to load license", error);
      return null;
    });
  if (licenseText) {
    contentContainer.innerHTML = `<pre>${licenseText}</pre>`;
  } else {
    contentContainer.innerHTML = `<p>Source : NeuroTech Commons – CC BY 4.0.</p>`;
  }
  dialog.showModal();
}

function applyHighContrast(root, enabled) {
  root.classList.toggle("high-contrast", enabled);
}

function initLaser(container, laserElement) {
  return {
    enable() {
      laserElement.hidden = false;
      container.addEventListener("pointermove", move);
    },
    disable() {
      laserElement.hidden = true;
      container.removeEventListener("pointermove", move);
    },
  };

  function move(event) {
    const rect = container.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    laserElement.style.left = `${x}px`;
    laserElement.style.top = `${y}px`;
  }
}

async function loadJsPDF() {
  if (window.jspdf) {
    return window.jspdf;
  }
  await import(JSPDF_URL);
  return window.jspdf;
}

function captureCanvas(renderer) {
  return renderer.domElement.toDataURL("image/png");
}

function getMeshList(nodeMap) {
  const meshes = [];
  nodeMap.forEach(node => {
    if (node.isMesh) {
      meshes.push(node);
    }
  });
  return meshes;
}

export async function initAnatomy3D(rootElement, options = {}) {
  if (!rootElement || initialized) {
    return;
  }
  initialized = true;
  ensureStyles();

  const loaderElement = rootElement.querySelector("[data-loader]");
  const loaderBar = rootElement.querySelector(".loader-bar");
  const loaderText = rootElement.querySelector("[data-loader-text]");
  const canvas = rootElement.querySelector("[data-renderer]");
  let fallback = rootElement.querySelector("[data-fallback]");
  const ribbon = rootElement.querySelector("[data-anatomy3d-mode-ribbon]");
  const sceneList = rootElement.querySelector("[data-scene-list]");
  const sceneNotes = rootElement.querySelector("[data-scene-notes]");
  const sceneQuestions = rootElement.querySelector("[data-scene-questions]");
  const sceneMyths = rootElement.querySelector("[data-scene-myths]");
  const layerList = rootElement.querySelector("[data-layer-list]");
  const searchInput = rootElement.querySelector("[data-search-input]");
  const searchSuggestions = rootElement.querySelector("[data-search-suggestions]");
  const glossaryContainer = rootElement.querySelector("[data-glossary]");
  const annotationList = rootElement.querySelector("[data-annotation-list]");
  const annotationsPanel = rootElement.querySelector("[data-annotations]");
  const captureButtons = rootElement.querySelector("[data-captures]");
  const snapshotsList = rootElement.querySelector("[data-snapshot-list]");
  const sequencesContainer = rootElement.querySelector("[data-sequence-editor]");
  const advancedOptions = rootElement.querySelector("[data-advanced-options]");
  const creditsDialog = rootElement.querySelector("[data-credits-dialog]");
  const creditsContent = rootElement.querySelector("[data-credits-content]");
  const selftestDialog = rootElement.querySelector("[data-selftest-dialog]");
  const loaderContainer = rootElement.querySelector("[data-canvas-container]");
  const laserElement = rootElement.querySelector("[data-laser]");

  const fallbackInfo = await prepareFallbackElement(fallback);
  fallback = fallbackInfo.element;
  const fallbackMessage = fallbackInfo.message;

  function showFallback(message = "Affichage 3D indisponible.") {
    loaderElement.hidden = true;
    if (fallback) {
      if (fallbackMessage) {
        fallbackMessage.textContent = message;
      }
      fallback.hidden = false;
      ensureRetryButton(fallback);
      return;
    }
    let inline = rootElement.querySelector("[data-fallback-inline]");
    if (!inline) {
      inline = document.createElement("div");
      inline.className = "anatomy3d__fallback-inline";
      inline.dataset.fallbackInline = "true";
      const paragraph = document.createElement("p");
      paragraph.className = "placeholder";
      paragraph.dataset.fallbackInlineMessage = "true";
      inline.appendChild(paragraph);
      loaderContainer.appendChild(inline);
    }
    const inlineMessage = inline.querySelector("[data-fallback-inline-message]");
    if (inlineMessage) {
      inlineMessage.textContent = message;
    } else {
      inline.textContent = message;
    }
    inline.hidden = false;
    ensureRetryButton(inline);
  }

  try {
    const flags = options?.flags ?? (await fetchJSON(FEATURE_FLAGS_URL, {}));
    if (flags && flags.anatomy3d_enabled === false) {
      rootElement.innerHTML = `<p class="placeholder">Module anatomie désactivé par configuration.</p>`;
      return;
    }

    const telemetryEnabled = flags?.anatomy3d_enable_telemetry !== false;
    if (advancedOptions) {
      advancedOptions.hidden = !Boolean(flags?.anatomy3d_allow_advanced_mode);
    }

    const store = createStateStore({
      lowPowerMode: Boolean(flags?.anatomy3d_low_power_mode),
    });
    if (telemetryEnabled) {
      store.incrementOpen();
    }
    updateRibbon(ribbon, store.state.mode);

    const prefs = {
      highContrast: store.state.highContrast,
      laserPointer: store.state.laserPointer,
    };
    applyHighContrast(rootElement, prefs.highContrast);

    const laser = initLaser(loaderContainer, laserElement);
    if (prefs.laserPointer) {
      laser.enable();
    }

    if (!supportsWebGL()) {
      showFallback("WebGL non disponible sur cet appareil.");
      return;
    }

    const renderer = createRenderer(canvas, store.state.lowPowerMode);
    const scene = createScene(store.state.lowPowerMode);
    const camera = new THREE.PerspectiveCamera(40, canvas.clientWidth / canvas.clientHeight, 0.1, 100);
    camera.position.set(0, 1.6, 3);

    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = !store.state.lowPowerMode;
    controls.dampingFactor = 0.05;
    controls.target.set(0, 1.1, 0);
    controls.update();

    const raycaster = createRaycaster(camera);
    const gltfLoader = new GLTFLoader();
    await configureDracoLoader(gltfLoader);
    gltfLoader.setMeshoptDecoder(MeshoptDecoder);

    let rootScene;
    let nodeMap = new Map();
    let meshes = [];
    let sceneLoader;
    const annotationMarkers = new Map();
    const markerGeometry = new THREE.SphereGeometry(0.015, 14, 14);

    function clearAnnotationMarkers() {
      annotationMarkers.forEach(marker => {
        if (marker.material) {
          marker.material.dispose?.();
        }
        scene.remove(marker);
      });
      annotationMarkers.clear();
    }

    function addAnnotationMarker(annotation) {
      if (!rootScene || !annotation?.position) {
        return;
      }
      const material = new THREE.MeshBasicMaterial({ color: 0xff5f7a });
      const marker = new THREE.Mesh(markerGeometry, material);
      marker.position.fromArray(annotation.position);
      marker.userData.annotationId = annotation.id;
      scene.add(marker);
      annotationMarkers.set(annotation.id, marker);
    }

    function renderAnnotationMarkers() {
      clearAnnotationMarkers();
      if (!rootScene) {
        return;
      }
      store.state.annotations.forEach(addAnnotationMarker);
    }

    const modelAvailable = await assetExists(MODEL_URL);
    if (!modelAvailable) {
      console.error(LOG_PREFIX, `model asset missing at ${MODEL_URL}`);
      showFallback("Modèle 3D introuvable.");
      return;
    }

    gltfLoader.load(
      MODEL_URL,
      gltf => {
        rootScene = gltf.scene;
        nodeMap = prepareNodeIndex(rootScene);
        meshes = getMeshList(nodeMap);
        scene.add(rootScene);
        loaderElement.hidden = true;
        const currentScene = sceneLoader.getCurrentScene?.();
        if (currentScene) {
          sceneLoader.applyScene(currentScene);
        }
        renderAnnotationMarkers();
        render();
      },
      event => {
        if (!event.total) {
          return;
        }
        const progress = Math.round((event.loaded / event.total) * 100);
        loaderBar.style.transform = `scaleX(${progress / 100})`;
        loaderBar.setAttribute("aria-valuenow", String(progress));
        loaderText.textContent = `Chargement ${progress}%`;
      },
      error => {
        console.error(LOG_PREFIX, "unable to load model", error);
        showFallback("Le modèle 3D n'a pas pu être chargé.");
      }
    );

    const resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        if (entry.target !== loaderContainer) {
          continue;
        }
        const { width, height } = entry.contentRect;
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height, false);
      }
    });
    resizeObserver.observe(loaderContainer);

    function render() {
      requestAnimationFrame(render);
      renderer.render(scene, camera);
    }

    sceneLoader = createSceneLoader({
      setCamera: config => setCameraFromConfig({ camera, controls }, config),
      applyVisibility: entries => applyNodeVisibility(nodeMap, entries),
      applyOpacity: entries => applyNodeOpacity(nodeMap, entries),
      updateContent: scene => updateNotes({ scene, notesContainer: sceneNotes, questionsContainer: sceneQuestions, mythsContainer: sceneMyths }),
    });

    const [scenes, layers, glossary, synonyms, sequences] = await Promise.all([
      fetchJSON(`${CONFIG_BASE}/scenes.json`, []),
      fetchJSON(`${CONFIG_BASE}/layers.json`, []),
      fetchJSON(`${CONFIG_BASE}/glossary.json`, []),
      fetchJSON(`${CONFIG_BASE}/synonyms.json`, []),
      loadSequences(),
    ]);

    store.setScenes(scenes);
    store.setLayers(layers);
    store.setGlossary(glossary);
    store.setSynonyms(synonyms);
    store.setSequences(sequences);

    function renderScenes() {
      sceneList.innerHTML = "";
      store.state.scenes.forEach(sceneItem => {
        const button = document.createElement("button");
        button.className = "button secondary";
        button.type = "button";
        button.textContent = sceneItem.title;
        button.dataset.sceneId = sceneItem.id;
        if (sceneItem.id === store.state.sceneId) {
          button.classList.add("active");
        }
        const li = document.createElement("li");
        li.appendChild(button);
        sceneList.appendChild(li);
      });
    }

    function renderLayers() {
      layerList.innerHTML = "";
      store.state.layers.forEach(group => {
        const item = document.createElement("div");
        item.className = "layer-item";
        const label = document.createElement("label");
        label.className = "toggle";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = group.defaultVisible !== false;
        input.dataset.layerId = group.id;
        label.appendChild(input);
        label.appendChild(document.createTextNode(group.label));
        const actions = document.createElement("div");
        actions.innerHTML = `<button type="button" class="ghost" data-layer-isolate="${group.id}">Solo</button>`;
        item.append(label, actions);
        layerList.appendChild(item);
      });
    }

    function renderAnnotations() {
      annotationList.innerHTML = "";
      if (!store.state.annotations.length) {
        annotationList.innerHTML = `<li class="muted">Aucune annotation enregistrée.</li>`;
        renderAnnotationMarkers();
        return;
      }
      store.state.annotations.forEach(annotation => {
        const li = document.createElement("li");
        li.className = "annotation-item";
        li.innerHTML = `
          <span>
            <strong>${annotation.title || annotation.id}</strong>
            ${annotation.description ? `<div class="muted">${annotation.description}</div>` : ""}
          </span>
          <span>
            <button type="button" class="ghost" data-annotation="${annotation.id}" data-action="edit">Éditer</button>
            <button type="button" class="ghost" data-annotation="${annotation.id}" data-action="focus">Voir</button>
            <button type="button" class="ghost" data-annotation="${annotation.id}" data-action="delete">Supprimer</button>
          </span>`;
        annotationList.appendChild(li);
      });
      renderAnnotationMarkers();
    }

    function renderSnapshots() {
      snapshotsList.innerHTML = "";
      if (!store.state.snapshots.length) {
        snapshotsList.innerHTML = `<li class="muted">Aucun snapshot.</li>`;
        return;
      }
      store.state.snapshots.forEach(snapshot => {
        const li = document.createElement("li");
        li.className = "snapshot-item";
        li.innerHTML = `
          <span>${snapshot.title}</span>
          <span>
            <button type="button" class="button secondary" data-snapshot="${snapshot.id}" data-action="restore">Restaurer</button>
            <button type="button" class="ghost" data-snapshot="${snapshot.id}" data-action="delete">Supprimer</button>
          </span>`;
        snapshotsList.appendChild(li);
      });
    }

    function renderSearchSuggestions(matches) {
      if (!matches.length) {
        searchSuggestions.hidden = true;
        searchSuggestions.innerHTML = "";
        return;
      }
      searchSuggestions.innerHTML = matches
        .map(match => `<li tabindex="0" data-key="${match.key}">${match.label_fr}</li>`)
        .join("");
      searchSuggestions.hidden = false;
    }

    function applySnapshot(snapshot) {
      if (!snapshot) {
        return;
      }
      setCameraFromConfig({ camera, controls }, snapshot.camera);
      applyNodeVisibility(nodeMap, snapshot.visibility || []);
      applyNodeOpacity(nodeMap, snapshot.opacity || []);
    }

    renderScenes();
    renderLayers();
    renderAnnotations();
    renderSnapshots();

    const sequenceEditor = createSequenceEditor({
      store,
      container: sequencesContainer,
      onPlaySnapshot: step => {
        const snapshot = store.state.snapshots.find(item => item.id === step.snapshot_id);
        if (snapshot) {
          applySnapshot(snapshot);
        }
      },
      downloadFile,
    });

    function handleSceneSelection(id) {
      const nextScene = store.state.scenes.find(sceneItem => sceneItem.id === id);
      if (!nextScene) {
        return;
      }
      store.selectScene(id);
      sceneLoader.applyScene(nextScene);
      renderScenes();
    }

    if (store.state.sceneId) {
      const initialScene = store.state.scenes.find(sceneItem => sceneItem.id === store.state.sceneId);
      if (initialScene) {
        sceneLoader.applyScene(initialScene);
      }
    }

    sceneList.addEventListener("click", event => {
      const button = event.target.closest("button[data-scene-id]");
      if (!button) {
        return;
      }
      handleSceneSelection(button.dataset.sceneId);
    });

    rootElement.querySelector('[data-action="reset-scene"]').addEventListener("click", () => {
      sceneLoader.resetScene();
    });

    layerList.addEventListener("change", event => {
      if (event.target.matches('input[type="checkbox"][data-layer-id]')) {
        const id = event.target.dataset.layerId;
        const group = store.state.layers.find(layer => layer.id === id);
        if (group) {
          applyLayerVisibility(nodeMap, group, event.target.checked);
        }
      }
    });

    layerList.addEventListener("click", event => {
      if (event.target.matches('[data-layer-isolate]')) {
        const id = event.target.dataset.layerIsolate;
        const group = store.state.layers.find(layer => layer.id === id);
        if (group) {
          soloLayer(nodeMap, group, store.state.layers);
        }
      }
    });

    rootElement.querySelector('[data-action="isolate-group"]').addEventListener("click", () => {
      const checked = layerList.querySelector('input[type="checkbox"][data-layer-id]:checked');
      if (!checked) {
        return;
      }
      const group = store.state.layers.find(layer => layer.id === checked.dataset.layerId);
      if (group) {
        soloLayer(nodeMap, group, store.state.layers);
      }
    });

    rootElement.querySelector('[data-action="ghost-others"]').addEventListener("click", () => {
      const checked = layerList.querySelector('input[type="checkbox"][data-layer-id]:checked');
      if (!checked) {
        return;
      }
      const group = store.state.layers.find(layer => layer.id === checked.dataset.layerId);
      if (group) {
        ghostLayers(nodeMap, group, store.state.layers, 0.2);
      }
    });

    function findGlossaryMatches(term) {
      if (!term) {
        return [];
      }
      const normalized = normalizeText(term);
      const results = [];
      store.state.glossary.forEach(entry => {
        if (normalizeText(entry.label_fr).includes(normalized)) {
          results.push(entry);
          return;
        }
        const synonyms = store.state.synonymsMap.get(entry.key) || [];
        if (synonyms.some(syn => normalizeText(syn).includes(normalized))) {
          results.push(entry);
        }
      });
      return results.slice(0, 6);
    }

    function focusStructure(key) {
      const entry = store.state.glossaryMap.get(key);
      updateGlossary(glossaryContainer, entry);
      const node = nodeMap.get(entry?.key?.toUpperCase()) || nodeMap.get(entry?.key);
      if (node) {
        highlightNode(node);
        const bounding = new THREE.Box3().setFromObject(node);
        const center = new THREE.Vector3();
        bounding.getCenter(center);
        controls.target.lerp(center, 0.4);
        controls.update();
      }
      searchSuggestions.hidden = true;
    }

    searchInput.addEventListener("input", debounce(event => {
      const matches = findGlossaryMatches(event.target.value);
      renderSearchSuggestions(matches);
    }));

    searchSuggestions.addEventListener("click", event => {
      const item = event.target.closest("li[data-key]");
      if (!item) {
        return;
      }
      focusStructure(item.dataset.key);
    });

    searchSuggestions.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        const item = event.target.closest("li[data-key]");
        if (item) {
          focusStructure(item.dataset.key);
        }
      }
    });

    annotationsPanel.querySelector('[data-action="export-annotations"]').addEventListener("click", () => {
      downloadFile(JSON.stringify(store.state.annotations, null, 2), "anatomy3d-annotations.json", "application/json");
    });

    annotationsPanel.querySelector('[data-action="import-annotations"] input').addEventListener("change", async event => {
      const file = event.target.files?.[0];
      if (!file) {
        return;
      }
      const text = await file.text();
      try {
        const data = JSON.parse(text);
        if (Array.isArray(data)) {
          store.setAnnotations(data);
          renderAnnotations();
        }
      } catch (error) {
        console.error(LOG_PREFIX, "Import annotations failed", error);
      }
    });

    annotationList.addEventListener("click", event => {
      const action = event.target.dataset.action;
      const id = event.target.dataset.annotation;
      const annotation = store.state.annotations.find(item => item.id === id);
      if (!annotation) {
        return;
      }
      if (action === "delete") {
        store.deleteAnnotation(id);
        renderAnnotations();
      }
      if (action === "focus") {
        setCameraFromConfig({ camera, controls }, annotation.camera);
      }
      if (action === "edit") {
        const description = prompt("Annotation", annotation.description || "");
        if (description !== null) {
          store.updateAnnotation(id, { description });
          renderAnnotations();
        }
      }
    });

    snapshotsList.addEventListener("click", event => {
      const action = event.target.dataset.action;
      const id = event.target.dataset.snapshot;
      const snapshot = store.state.snapshots.find(item => item.id === id);
      if (!snapshot) {
        return;
      }
      if (action === "delete") {
        store.removeSnapshot(id);
        renderSnapshots();
      }
      if (action === "restore") {
        applySnapshot(snapshot);
      }
    });

    rootElement.querySelector('[data-action="add-snapshot"]').addEventListener("click", () => {
      const snapshot = {
        id: nanoid("snapshot"),
        title: `Snapshot ${store.state.snapshots.length + 1}`,
        camera: {
          position: camera.position.toArray(),
          target: getCameraTarget(controls).toArray(),
          fov: camera.fov,
        },
        ...extractVisibility(nodeMap),
      };
      store.addSnapshot(snapshot);
      renderSnapshots();
    });

    rootElement.querySelector('[data-action="export-snapshots"]').addEventListener("click", () => {
      downloadFile(JSON.stringify(store.state.snapshots, null, 2), "anatomy3d-snapshots.json", "application/json");
    });

    rootElement.querySelector('[data-action="import-snapshots"] input').addEventListener("change", async event => {
      const file = event.target.files?.[0];
      if (!file) {
        return;
      }
      const text = await file.text();
      try {
        const data = JSON.parse(text);
        if (Array.isArray(data)) {
          store.setSnapshots(data);
          renderSnapshots();
        }
      } catch (error) {
        console.error(LOG_PREFIX, "Import snapshots failed", error);
      }
    });

    captureButtons.querySelector('[data-action="capture-png"]').addEventListener("click", async () => {
      const dataUrl = captureCanvas(renderer);
      const response = await fetch(dataUrl);
      const blob = await response.blob();
      downloadFile(blob, `anatomy3d-${Date.now()}.png`, "image/png");
      if (telemetryEnabled) {
        store.recordCapture();
      }
    });

    captureButtons.querySelector('[data-action="export-pdf"]').addEventListener("click", async () => {
      if (flags?.anatomy3d_enable_pdf_export === false) {
        return;
      }
      const jspdf = await loadJsPDF();
      const { jsPDF } = jspdf;
      const doc = new jsPDF({ orientation: "landscape" });
      const before = {
        camera: {
          position: camera.position.toArray(),
          target: getCameraTarget(controls).toArray(),
          fov: camera.fov,
        },
        ...extractVisibility(nodeMap),
      };
      const captures = store.state.snapshots.slice(0, 3).map(snapshot => {
        applySnapshot(snapshot);
        return captureCanvas(renderer);
      });
      captures.forEach((image, index) => {
        if (index > 0) {
          doc.addPage();
        }
        doc.addImage(image, "PNG", 10, 10, 270, 150);
        doc.text(store.state.snapshots[index]?.title || `Capture ${index + 1}`, 10, 170);
      });
      applySnapshot(before);
      doc.save("anatomy3d-handout.pdf");
    });

    const linkToNotesButton = captureButtons.querySelector('[data-action="link-to-notes"]');
    linkToNotesButton.disabled = !Boolean(flags?.anatomy3d_link_to_notes);

    sequencesContainer.querySelector('[data-action="open-sequence-editor"]').addEventListener("click", () => {
      sequenceEditor.open();
    });

    captureButtons.querySelector('[data-action="capture-png"]').setAttribute("title", "Raccourci : P");

    rootElement.addEventListener("keydown", event => {
      if (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA") {
        return;
      }
      switch (event.key.toLowerCase()) {
        case "r":
          sceneLoader.resetScene();
          break;
        case "i":
          const checked = layerList.querySelector('input[type="checkbox"][data-layer-id]:checked');
          if (checked) {
            const group = store.state.layers.find(layer => layer.id === checked.dataset.layerId);
            if (group) {
              soloLayer(nodeMap, group, store.state.layers);
            }
          }
          break;
        case "g":
          const target = layerList.querySelector('input[type="checkbox"][data-layer-id]:checked');
          if (target) {
            const group = store.state.layers.find(layer => layer.id === target.dataset.layerId);
            if (group) {
              ghostLayers(nodeMap, group, store.state.layers, 0.2);
            }
          }
          break;
        case "s":
          rootElement.querySelector('[data-action="add-snapshot"]').click();
          break;
        case "p":
          captureButtons.querySelector('[data-action="capture-png"]').click();
          break;
        default:
          break;
      }
    });

    const canvasClick = event => {
      if (!meshes.length) {
        return;
      }
      const hit = raycaster.cast(event, meshes);
      if (!hit) {
        return;
      }
      const annotation = {
        id: nanoid("annotation"),
        title: hit.object.name || "Annotation",
        position: hit.point.toArray(),
        camera: {
          position: camera.position.toArray(),
          target: getCameraTarget(controls).toArray(),
          fov: camera.fov,
        },
        description: "",
      };
      const text = prompt("Ajouter une annotation", "");
      if (text !== null) {
        annotation.description = text;
      }
      store.addAnnotation(annotation);
      renderAnnotations();
    };

    canvas.addEventListener("dblclick", canvasClick);

    const creditsButton = rootElement.querySelector('[data-action="open-credits"]');
    creditsButton.addEventListener("click", () => loadCredits(creditsDialog, creditsContent));

    creditsDialog.addEventListener("click", event => {
      if (event.target.matches('[data-action="close-dialog"]')) {
        creditsDialog.close();
      }
    });

    const selftestButton = rootElement.querySelector('[data-action="open-selftest"]');
    selftestButton.addEventListener("click", () => selftestDialog.showModal());
    selftestDialog.addEventListener("click", event => {
      if (event.target.matches('[data-action="close-dialog"]')) {
        selftestDialog.close();
      }
    });

    attachLinkHandlers(glossaryContainer);

    if (advancedOptions) {
      const highContrastInput = advancedOptions.querySelector('[data-pref="high-contrast"]');
      const laserInput = advancedOptions.querySelector('[data-pref="laser-pointer"]');

      if (highContrastInput) {
        highContrastInput.checked = store.state.highContrast;
        highContrastInput.addEventListener("change", () => {
          store.setPreferences({ highContrast: highContrastInput.checked });
          applyHighContrast(rootElement, highContrastInput.checked);
        });
      }

      if (laserInput) {
        laserInput.checked = store.state.laserPointer;
        laserInput.addEventListener("change", () => {
          store.setPreferences({ laserPointer: laserInput.checked });
          if (laserInput.checked) {
            laser.enable();
          } else {
            laser.disable();
          }
        });
      }
    }

  } catch (error) {
    console.error(LOG_PREFIX, "initialization failed", error);
    showFallback("Le module 3D n'a pas pu démarrer.");
  }
}
