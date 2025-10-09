# Guide de dépannage

## « Documents d’aide ne se charge pas »

1. **Observer le bandeau interne** : si le module affiche un encart orange, relever la liste des assets manquants, sélecteurs absents ou doublons détectés. Le contenu provient de `validateTab()`.
2. **Vérifier les assets** : lancer `scripts/validate_tabs.py` pour confirmer que le dossier `client/static/tabs/documents_aide/` n’existe pas (sinon le supprimer).
3. **Contrôler la version des fichiers** : vérifier que `server/services/assets.py` a été relancé (le hash doit changer si `view.html` ou `style.css` a été modifié). En cas de doute, redémarrer le serveur Flask.
4. **Inspecter la console navigateur** : rechercher une entrée `module: 'documents_aide'` détaillant la phase (`fetch`, `http`, `selectors`, `validateTab`), le statut HTTP ou la liste des sélecteurs manquants.
5. **Tester l’onglet via Playwright** : exécuter `RUN_E2E=1 pytest tests/e2e/test_documents_aide_tab.py` pour reproduire automatiquement l’ouverture de l’onglet et vérifier la présence du sélecteur racine.

Si l’erreur persiste, s’assurer que l’API `/api/documents-aide/*` répond et que les patients de démonstration sont disponibles (`pytest tests/test_documents_aide.py`).
