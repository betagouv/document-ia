# Collection Bruno Document IA

## Installation de Bruno
1. Téléchargez Bruno depuis [usebruno.com/downloads](https://www.usebruno.com/downloads) et installez la version adaptée à votre OS.
2. Sur macOS vous pouvez aussi utiliser Homebrew :
   ```bash
   brew install --cask bruno
   ```

## Importer la collection Document IA
1. Clonez ce dépôt si ce n'est pas déjà fait, puis ouvrez le dossier `document-ia-api/bruno-api` dans Bruno.
2. Dans Bruno Desktop :
   - Cliquez sur **Open Collection**.
   - Sélectionnez ce dossier (qui contient les fichiers `.bru`).
   - La collection Document IA apparaît dans l'arborescence.
3. Avec le CLI Bruno (optionnel) :
   ```bash
   cd document-ia-api/bruno-api
   bruno run workflows/execute.bru
   ```

## Configuration
- Ajoutez votre clé API Document IA dans l'environnement Bruno (section **Environments**).
- Mettez à jour la variable `baseUrl` pour pointer vers votre instance (ex. `http://localhost:8000`).

## Exécution rapide
- Sélectionnez une requête (ex. `POST /workflows/{id}/execute`).
- Renseignez les variables `workflow_id`, `file`, `metadata`.
- Cliquez sur **Send** pour tester l'API.
