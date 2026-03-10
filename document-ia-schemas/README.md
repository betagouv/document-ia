# document-ia-schemas  [![Python Version](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/) [![Poetry](https://img.shields.io/badge/package%20manager-poetry-blue)](https://python-poetry.org/)

Ensemble de modèles de documents utilisés par Document-IA pour l’extraction de données depuis des pièces justificatives françaises.

Chaque type de document est décrit par un schéma Pydantic (métadonnées + JSON Schema) afin de:
- standardiser les champs attendus (nommage clair, alias lisibles, exemples),
- générer des prompts d’extraction précis,
- produire un JSON Schema partageable entre services (validation, contrats d’API, UI de saisie/contrôle, etc.).


## ✨ Caractéristiques
- Schémas typés et versionnés (Pydantic v2)
- Méta-informations pour guider la détection/description d’un document
- Export direct en JSON Schema
- API simple pour résoudre un schéma par son nom (ex: "cni", "passeport")


## 📦 Installation

Selon votre contexte, vous pouvez installer le package depuis une source Git ou un chemin local.

- Avec Poetry (recommandé)

```bash
# Depuis un dépôt Git (adaptez l’URL de votre dépôt)
poetry add git+https://github.com/ORG/REPO.git#subdirectory=documentAI/document-ia-schemas

# Ou depuis un chemin local (monorepo)
poetry add ../documentAI/document-ia-schemas
```

- Avec pip

```bash
# Depuis Git (adaptez l’URL)
pip install "git+https://github.com/ORG/REPO.git#subdirectory=documentAI/document-ia-schemas"

# Ou depuis un chemin local
pip install -e ../documentAI/document-ia-schemas
```

Astuce: si vous utilisez un monorepo, préférez l’ajout par chemin relatif pour rester synchronisé pendant le développement.


## 🧰 Utilisation rapide

### 1) Résoudre un schéma par nom

```python
from document_ia_schemas import resolve_extract_schema

# Exemples: "cni", "passeport", "permis_conduire", "avis_imposition"
schema = resolve_extract_schema("cni")

# Métadonnées pour générer un prompt d’extraction
info = schema.get_document_description_dict()
# => {"type": "cni", "name": "Carte nationale d'identité", "description": [ ... ]}

# JSON Schema du modèle de données
json_schema = schema.get_json_schema_dict()
# => dict prêt à être sérialisé en JSON
```

### 2) Importer un type explicitement

```python
from document_ia_schemas.cni import CNIExtractSchema

schema = CNIExtractSchema()
print(schema.get_document_description_dict())
print(schema.get_json_schema_dict())
```

## 📚 Types de documents inclus

| Identifiant | Nom | Module |
|-------------|-----|--------|
| `cni` | Carte nationale d’identité | `document_ia_schemas.cni` |
| `passeport` | Passeport | `document_ia_schemas.passeport` |
| `permis_conduire` | Permis de conduire | `document_ia_schemas.permis_conduire` |
| `avis_imposition` | Avis d’imposition | `document_ia_schemas.avis_imposition` |

Chaque type expose un modèle Pydantic décrivant les champs standardisés, avec alias et exemples pour faciliter les prompts.


## 🔎 API de base

Tous les schémas héritent de `BaseDocumentTypeSchema` et exposent:
- `get_document_description_dict() -> dict`: métadonnées (type, nom, description…)
- `get_json_schema_dict() -> dict`: JSON Schema du modèle Pydantic

Utilitaires fournis:
- `resolve_extract_schema(name: str) -> BaseDocumentTypeSchema`: importe le module du type et retourne l’instance du schéma `*ExtractSchema` correspondant.


## 🗂️ Structure du projet

```
src/
  document_ia_schemas/
    __init__.py                     # resolve_extract_schema()
    base_document_type_schema.py    # Classe de base (Pydantic + helpers)
    cni.py
    passeport.py
    permis_conduire.py
    avis_imposition.py
```


## 🧪 Développement

Pré-requis: Python 3.13+, Poetry

```bash
# Installer les dépendances
poetry install

# Lint
poetry run ruff check .
poetry run ruff format --check .

# Tests
poetry run pytest -v
```


## 🤝 Contribution

Les contributions sont les bienvenues (ajout d’un nouveau type de document, corrections, docs). Veuillez lire le guide de contribution avant toute PR:

- Voir [CONTRIBUTING.md](CONTRIBUTING.md)


## 📄 Licence

MIT — voir le fichier LICENSE.
