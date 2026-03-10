# Guide de contribution

Merci de votre intérêt pour contribuer à **document-ia-schemas** ! 🎉

Ce dépôt centralise les schémas de documents utilisés par Document‑IA pour l’extraction de données. Chaque type de document est décrit via un modèle Pydantic et un schéma « ExtractSchema » qui expose des métadonnées et un JSON Schema exploitable par les autres services.

Ce guide explique comment proposer un nouveau type de document, les conventions à suivre, et le processus d’intégration côté équipe Document‑IA.


## 📋 Table des matières
- [Ajouter un nouveau type de document](#ajouter-un-nouveau-type-de-document)
- [Structure d’un schéma de document](#structure-dun-schéma-de-document)
- [Étapes détaillées](#étapes-détaillées)
- [Tests locaux et qualité](#tests-locaux-et-qualité)
- [Processus d’intégration (PR → validation → merge)](#processus-dintégration-pr--validation--merge)
- [Bonnes pratiques](#bonnes-pratiques)
- [Checklist avant de soumettre](#checklist-avant-de-soumettre)
- [Questions](#questions)


## 🆕 Ajouter un nouveau type de document

Pour ajouter le support d’un nouveau type (ex: « carte_grise », « justificatif_domicile », etc.), procédez ainsi :

1) Créer un fichier dans `src/document_ia_schemas/` nommé d’après l’identifiant du type, en snake_case. Exemple :
   - `src/document_ia_schemas/carte_grise.py`

2) Dans ce fichier, définir :
   - un modèle Pydantic `<Nom>Model` décrivant les champs attendus,
   - une classe `<Nom>ExtractSchema` héritant de `BaseDocumentTypeSchema[<Nom>Model]` qui expose:
     - `type` (identifiant technique, ex: "carte_grise"),
     - `name` (nom lisible, ex: "Carte grise"),
     - `description` (liste d’indices textuels pour décrire le document),
     - `document_model` (référence vers le modèle Pydantic).

3) Ouvrir une Pull Request (PR) sur ce dépôt avec votre nouveau fichier. L’équipe Document‑IA s’occupera de :
   - la revue technique (nomenclature, types, descriptions),
   - l’alignement métier (cohérence avec les autres types),
   - l’intégration dans la solution Document‑IA (prompts, validation, diffusion).


## 📦 Structure d’un schéma de document

Voici un squelette minimal réutilisable. Adaptez les champs, descriptions, alias et exemples.

```python
# src/document_ia_schemas/carte_grise.py
from typing import Optional, Type
from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema


class CarteGriseModel(BaseModel):
    numero_immatriculation: str = Field(
        description="Numéro d'immatriculation du véhicule (format AA-123-AA)",
        alias="Numéro d'immatriculation",
        examples=["AB-123-CD"],
    )
    nom_titulaire: str = Field(
        description="Nom du titulaire du certificat d'immatriculation",
        alias="Nom du titulaire",
        examples=["DUPONT"],
    )
    adresse_titulaire: Optional[str] = Field(
        default=None,
        description="Adresse du titulaire. Si absente, renseigner `null`.",
        alias="Adresse du titulaire",
        examples=["10 Rue Exemple, 75001 Paris"],
    )
    date_premiere_mise_en_circulation: Optional[str] = Field(
        default=None,
        description="Date de 1ère mise en circulation (JJ/MM/AAAA). Si absente, `null`.",
        alias="Date de première mise en circulation",
        examples=["01/06/2018"],
    )


class CarteGriseExtractSchema(BaseDocumentTypeSchema[CarteGriseModel]):
    type: str = "carte_grise"
    name: str = "Carte grise"
    description: list[str] = [
        "Certificat d'immatriculation du véhicule",
        'Peut contenir la mention "République Française"',
        "Contient l'immatriculation, le titulaire, l'adresse, des dates clés",
    ]

    document_model: Type[CarteGriseModel] = CarteGriseModel
```

- `alias` dans `Field(...)` correspond à un libellé lisible, utile pour les prompts/output.
- Les `examples` aident à documenter et guider l’extraction.
- Les champs facultatifs doivent avoir `Optional[...]` + `default=None` + description claire.


## 🔧 Étapes détaillées

1) Créer le fichier du type dans `src/document_ia_schemas/`.
2) Définir le modèle Pydantic avec des descriptions en français, alias explicites et exemples.
3) Définir la classe `*ExtractSchema` avec `type`, `name`, `description` et `document_model`.
4) Optionnel: mettre à jour la table des types dans le `README.md` (section « Types de documents inclus »).
5) Lancer les vérifications locales (ruff/pytest) — voir section suivante.
6) Ouvrir une PR claire et concise.


## 🧪 Tests locaux et qualité

Pré-requis: Python 3.13+, Poetry

```bash
poetry install
poetry run ruff check .
poetry run ruff format --check .
poetry run pytest -v
```

Conseils:
- Respectez le typage et la cohérence des formats (dates en `JJ/MM/AAAA`, numériques en `float` pour montants…).
- Préférez des noms de champs en `snake_case` et des alias lisibles pour l’utilisateur final.


## 🚀 Processus d’intégration (PR → validation → merge)

1) Ouvrez une **Pull Request** sur ce dépôt avec votre nouveau type.
   - Incluez une description du document, les champs ajoutés et, si possible, un exemple (anonymisé) d’output attendu.
   - Suivez une convention de commit simple: `feat: nouveau type carte_grise`, `docs: maj readme`, `fix: correction alias`, etc.

2) L’équipe **Document‑IA** effectue la revue et la validation métier:
   - Vérifications de la nomenclature, alias, exemples, cohérence avec les autres types.
   - Tests de génération de prompts et validation de JSON Schema dans la chaîne Document‑IA.

3) Après validation, l’équipe merge la PR puis déclenche l’**intégration** dans la solution Document‑IA.
   - Cette étape est gérée par l’équipe (déploiement, synchronisation des schémas, release si nécessaire).

4) Publication / versioning
   - Le versioning suit une logique pragmatique (semver quand applicable).
   - Les changements de schémas peuvent entraîner une montée de version mineure ou majeure selon l’impact.


## ✅ Bonnes pratiques

- Champs
  - Utilisez des descriptions précises, en français, orientées « signaux visuels/texte » utiles pour la détection.
  - Distinguez clairement obligatoires vs. facultatifs (avec `Optional` + `default=None`).
  - Ajoutez des `examples` réalistes (mais anonymisés).

- Nommage
  - Fichiers en `snake_case` (ex: `justificatif_domicile.py`).
  - Classe modèle: `JustificatifDomicileModel`.
  - Classe schéma: `JustificatifDomicileExtractSchema`.
  - Attribut `type` en snake_case: `"justificatif_domicile"`.

- Cohérence
  - Réutilisez les libellés (`alias`) déjà rencontrés quand ils ont le même sens.
  - Gardez les formats homogènes (dates, montants, identifiants).


## 🔍 Checklist avant de soumettre

- [ ] Le fichier du type est dans `src/document_ia_schemas/<type>.py`
- [ ] Le modèle Pydantic contient des `Field` avec `description`, `alias`, `examples`
- [ ] Les champs facultatifs sont bien `Optional[...]` avec `default=None`
- [ ] La classe `<Nom>ExtractSchema` définit `type`, `name`, `description`, `document_model`
- [ ] `poetry run ruff check .` passe
- [ ] `poetry run ruff format --check .` passe
- [ ] `poetry run pytest -v` passe (s’il y a des tests)
- [ ] PR ouverte avec un titre et une description clairs


## 💬 Questions

Si vous avez des questions ou besoin d’aide :
- Ouvrez une **issue** sur GitHub
- Ou mentionnez l’équipe **Document‑IA** directement dans la PR

Merci pour votre contribution ! 🙏
