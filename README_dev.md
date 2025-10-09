# Démarrage rapide Windows

1. `powershell -ExecutionPolicy Bypass -File scripts\setup-env.ps1`
2. `powershell -File scripts\run-dev.ps1` ou `scripts\run-dev.cmd`
3. Lancer `http://127.0.0.1:5000/?debug=1` dans un navigateur.
4. `scripts\smoke-test.ps1` vérifie `/`, `/api/health`, `/api/patients`.
5. `scripts\client-diag.ps1` ouvre Firefox (profil vierge) + snippet diagnostics.
6. `scripts\server-diag.ps1` affiche versions, variables et ports écoutés.

codex/attach-window.__diag-in-initdiagnosticspanel
## Support – raccourci diagnostics

Le panneau diagnostics expose maintenant `window.__diag` dans la console navigateur :

- `window.__diag.show()` force l'ouverture du panneau si un utilisateur l'a masqué.
- `window.__diag.hide()` referme le panneau après vérification.

Ce raccourci est utile au support pour guider les utilisateurs à distance sans leur faire chercher le bouton dans l'interface.
=======
## CI locale

Avant de pousser une modification, lancez la vérification combinée :

1. `python tools/check_patients_fs.py` — compile le dossier `server/` et confirme que le nombre de dossiers patients correspond à `/api/patients`.
2. `pytest` — exécute la batterie de tests serveur.
main

## Vérification manuelle – pré-session

Les nouveaux points d'entrée `/api/pre` permettent de préparer et d'enregistrer un briefing avant la séance. Pour les tester manuellement :

1. Lancer le serveur (`python server.py`) puis exécuter :
   ```bash
   curl -X POST http://127.0.0.1:5000/api/pre/prepare \
        -H "Content-Type: application/json" \
        -d '{"patientId":"PAT-001","contexts":[{"title":"Suivi","summary":"Dernière séance positive"}],"internalParams":{},"locale":"fr-FR"}'
   ```
   Vérifier que la réponse contient `ok: true`, un `plan.id` déterministe et les en-têtes `Cache-Control: no-store` / `application/json; charset=utf-8`.
2. Réinjecter le `plan` retourné dans :
   ```bash
   curl -X POST http://127.0.0.1:5000/api/pre/generate \
        -H "Content-Type: application/json" \
        -d '{"plan":{...}}'
   ```
   La réponse doit inclure `prompt` et un champ `path`.
3. Confirmer la persistance du fichier `instance/pre_sessions/<patientSlug>/<horodatage>.json` avec le plan et le prompt générés.
