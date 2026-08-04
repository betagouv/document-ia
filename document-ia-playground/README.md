# Document IA - Playground Public 🚀

Application Streamlit publique permettant de tester interactivement l'API Document IA.

## Fonctionnalités
- 🔐 **Multi-Environnements & Authentification** : Sélecteur d'environnement (Sandbox, Staging, Production ou URL personnalisée) et saisie sécurisée de la clé API.
- ⚡ **Exécuter un Workflow v2** : Téléversement de documents (fichier local ou URL), configuration dynamique des étapes et surcharges (overrides), aperçu des requêtes (cURL, TypeScript, Java) et exécution synchrone/asynchrone.
- 🔍 **Récupérer une exécution** : Interrogation directe de l'état et des résultats d'une exécution d'API via son `execution_id`.

## Lancement en local

```bash
# Avec UV
uv run streamlit run src/document_ia_playground/app.py
```
