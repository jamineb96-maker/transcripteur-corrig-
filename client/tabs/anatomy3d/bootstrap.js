import "three";
import "three/examples/jsm/controls/OrbitControls.js";
import "three/examples/jsm/loaders/GLTFLoader.js";
import "three/examples/jsm/loaders/DRACOLoader.js";
import "three/examples/jsm/libs/meshopt_decoder.module.js";

import { initAnatomy3D } from "/static/tabs/anatomy3d/index.js";

const BOOT_PREFIX = "[anatomy3d]";
const root = document.querySelector("[data-anatomy3d-root]");

if (root) {
  initAnatomy3D(root)
    .catch(error => {
      console.error(BOOT_PREFIX, "bootstrap failed", error);
    });
}
