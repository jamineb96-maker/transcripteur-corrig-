export function createSceneLoader({ setCamera, applyVisibility, applyOpacity, updateContent }) {
  let currentScene = null;

  function applyScene(scene) {
    if (!scene) {
      return;
    }
    currentScene = scene;
    if (scene.camera) {
      setCamera(scene.camera);
    }
    applyVisibility(scene.visibility || []);
    applyOpacity(scene.opacity || []);
    updateContent(scene);
  }

  function resetScene() {
    if (!currentScene) {
      return;
    }
    applyScene(currentScene);
  }

  return {
    applyScene,
    resetScene,
    getCurrentScene: () => currentScene,
  };
}
