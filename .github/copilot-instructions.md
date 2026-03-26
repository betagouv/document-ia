# CONTEXTE DU PROJET : DocumentIA

## 🎯 Mission
Je développe "DocumentIA", un service de l'État français permettant de classifier et d'extraire des informations depuis des documents administratifs scannés.
Nous migrons d'une approche "LLM Prompt Stuffing" (qui ne scale pas pour 100+ types de documents) vers une architecture basée sur la recherche vectorielle (k-NN) pour la classification, garantissant rapidité, scalabilité et respect strict du RGPD.

## 🛠️ Stack Technique
- **Langage :** Python 3
- **OCR :** Tesseract (via pytesseract)
- **Anonymisation (RGPD) :** Approche hybride (Regex) + LLM hébergé sur SecNumCloud (ou spaCy) pour remplacer les PII par des balises (ex: [NOM], [NIR]).
- **Embedding :** `BAAI/bge-m3` (HuggingFace, optimisé multilingue/français).
- **Base de données :** PostgreSQL avec l'extension `pgvector`.
- **Reranking :** `BAAI/bge-reranker-v2-m3` (HuggingFace) pour départager les Top-K résultats.

## 🏗️ Architecture et Workflow

Le système est divisé en deux flux principaux :

### 1. Flux d'Ingestion (Création de la base de référence)
Pour chaque document de notre dataset d'entraînement (environ 60 documents pour le PoC, avec plusieurs exemples par classe) :
1. Extraction du texte via OCR.
2. Anonymisation stricte du texte (remplacement des données personnelles par des balises génériques pour éviter les fuites et améliorer la généralisation).
3. Calcul de l'embedding du texte anonymisé via `bge-m3`.
4. Stockage dans PostgreSQL (pgvector) : On stocke X vecteurs par type de document (pas de vecteur moyen ! On utilise une logique k-NN).

### 2. Flux de Prédiction (Inférence en production)
Lorsqu'un usager soumet un nouveau document :
1. OCR du document.
2. (Optionnel selon perf) Anonymisation à la volée du texte.
3. Calcul de l'embedding du document.
4. Recherche de similarité vectorielle (Cosine Distance) dans pgvector pour récupérer les Top-K (ex: Top 5) documents les plus proches.
5. (Optionnel) Passage du texte OCR cible et des textes des Top-K candidats dans le reranker `bge-reranker-v2-m3` pour affiner le score.
6. Vote à la majorité / Sélection du meilleur score pour déterminer la classe finale du document.

## 🧑‍💻 Règles de développement
- Le code doit être robuste, typé (`typing`), et bien commenté.
- Une attention particulière doit être portée à la gestion des erreurs (ex: échec de l'OCR, base de données injoignable).
- Les données traitées sont sensibles (documents citoyens) : aucune donnée en clair ne doit fuiter dans les logs ou dans les vecteurs stockés.
