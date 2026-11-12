# document-ia-schemas  [![Python Version](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/) [![uv](https://img.shields.io/badge/package%20manager-uv-blue)](https://github.com/astral-sh/uv)

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

- Avec UV (recommandé)

```bash
# Depuis un dépôt Git (adaptez l’URL de votre dépôt)
uv add "git+https://github.com/ORG/REPO.git#subdirectory=documentAI/document-ia-schemas"

# Ou depuis un chemin local (monorepo)
uv add ../documentAI/document-ia-schemas
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
| `attestation_contrat_energie` | Attestation de contrat d'énergie | `document_ia_schemas.attestation_contrat_energie` |
| `attestation_hebergement` | Attestation d'hebergement | `document_ia_schemas.attestation_hebergement` |
| `avis_imposition` | Avis d'imposition | `document_ia_schemas.avis_imposition` |
| `bulletin_salaire` | Bulletin de salaire | `document_ia_schemas.bulletin_salaire` |
| `carte_grise` | Carte grise (Certificat d'immatriculation) | `document_ia_schemas.carte_grise` |
| `cni` | Carte nationale d'identité | `document_ia_schemas.cni` |
| `decision_comed` | Décision de la commission de médiation DALO | `document_ia_schemas.decision_comed` |
| `facture_energie` | Facture d'énergie | `document_ia_schemas.facture_energie` |
| `passeport` | Passeport | `document_ia_schemas.passeport` |
| `permis_conduire` | Permis de conduire | `document_ia_schemas.permis_conduire` |
| `quittance_loyer` | Quittance de loyer | `document_ia_schemas.quittance_loyer` |
| `taxe_fonciere` | Taxe fonciere | `document_ia_schemas.taxe_fonciere` |
| `visale_certificate` | Certificat de garantie Visale | `document_ia_schemas.visale_certificate` |

Chaque type expose un modèle Pydantic décrivant les champs standardisés, avec alias et exemples pour faciliter les prompts.


## 🔎 API de base

Tous les schémas héritent de `BaseDocumentTypeSchema` et exposent:
- `get_document_description_dict() -> dict`: métadonnées (type, nom, description…)
- `get_json_schema_dict() -> dict`: JSON Schema du modèle Pydantic

Utilitaires fournis:
- `resolve_extract_schema(name: str) -> BaseDocumentTypeSchema`: importe le module du type et retourne l’instance du schéma `*ExtractSchema` correspondant.

### Propriétés invalides et anomalies d'extraction

Le socle repose sur `InvalidProperty`, un modèle unique pour toute propriété candidate dont l'extraction échoue à la validation métier :

```python
class InvalidProperty(BaseModel):
    code: str
    raw_value: str
```

Pour les dates, lorsqu'une valeur candidate ne représente pas une date valide sur le calendrier, `FuzzyDate` instancie directement un `InvalidProperty` avec le code `DateAnomalyCode.INVALID_DATE` (`"invalid_date"`).

`FuzzyDate` conserve les dates valides et les valeurs absentes. Les formats
`AAAA-MM-JJ`, `JJ/MM/AAAA`, `JJ-MM-AAAA` et `JJ.MM.AAAA` restent acceptés,
y compris avec un jour ou un mois sur un chiffre.

Une date impossible ne remplace plus la valeur extraite et ne tente aucune correction automatique.
Le champ contient un objet `InvalidProperty`, conservé lors de la sérialisation :

```json
{
  "code": "invalid_date",
  "raw_value": "31/04/2026"
}
```

`raw_value` est la valeur candidate brute extraite du document. Les autres champs du document restent disponibles.

Dans les résultats de l'API v1 et v2, la propriété garde `type: "date"`, avec
`value: null` et cet objet dans `anomaly` :

```json
{
  "name": "date_naissance",
  "type": "date",
  "value": null,
  "anomaly": {
    "code": "invalid_date",
    "raw_value": "31/04/2026"
  }
}
```

Les dates valides gardent leur valeur ISO habituelle (`value: "2024-01-01"`) ; les valeurs absentes restent à `value: null`, sans champ `anomaly`.

**Limites :** un texte qui ne correspond à aucun format accepté reste une erreur
de validation. Les anciennes valeurs enregistrées sans leur candidate d'origine ne
peuvent pas être reconstituées.


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

Pré-requis: Python 3.13+, UV

```bash
# Installer les dépendances
uv sync

# Lint
uv run ruff check .
uv run ruff format --check .

# Tests
uv run pytest -v
```

### Impact sur les snapshots de prompts du worker

Les prompts d'extraction sont rendus à partir de ces schémas et figés dans des **snapshots** côté worker (`document-ia-worker/tests/snapshots/prompts/extraction/<type>.txt`). Toute modification d'un schéma (nouveau champ, renommage, description ou exemple modifié) change le prompt rendu et fait échouer le test de snapshot correspondant.

Voir la section « Tests & Prompt Snapshots » du `README.md` du worker pour le détail.

## 🤝 Contribution

Les contributions sont les bienvenues (ajout d’un nouveau type de document, corrections, docs). Veuillez lire le guide de contribution avant toute PR:

- Voir [CONTRIBUTING.md](CONTRIBUTING.md)


## 📄 Licence

MIT — voir le fichier LICENSE.
