// Playwright end‑to‑end test for the post‑session assistant
//
// Cette spécification illustre comment un test de bout en bout pourrait être structuré.
// Elle n'est pas exécutée automatiquement dans cette archive mais sert de base
// pour développer des tests UI réels.

const { test, expect } = require('@playwright/test');

test('post‑session flow yields stable artefacts', async ({ page }) => {
  // Lancez le serveur localement avant d'exécuter ce test.  L'URL
  // peut être personnalisée via la variable d'environnement BASE_URL.
  const baseUrl = process.env.BASE_URL || 'http://127.0.0.1:5000';
  // Étape 1 : ouverture de la page principale
  await page.goto(baseUrl);
  // On suppose qu'un bouton permet de charger un fichier audio.  Sélectionnons
  // l'échantillon court fourni dans samples/.
  const fileChooserPromise = page.waitForEvent('filechooser');
  await page.click('input[type="file"]');
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles('samples/sample_short.wav');
  // Attendre que la transcription se termine et que le plan soit affiché
  await page.waitForSelector('text=Plan de séance');
  // Stocker l'ID de session pour vérification
  const sessionId = await page.locator('[data-session-id]').innerText();
  // Rafraîchir la page pour simuler une reprise
  await page.reload();
  // Vérifier que l'application propose de reprendre la session
  await page.click('text=Reprendre la session');
  // L'ID de session doit rester identique et le mail doit être affiché
  const resumedId = await page.locator('[data-session-id]').innerText();
  expect(resumedId).toBe(sessionId);
  await expect(page.locator('h1')).toContainText('Compte‑rendu de séance');
});