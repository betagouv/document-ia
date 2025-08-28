# Document IA API

API minimaliste FastAPI avec authentification API_KEY et documentation automatique.

## Structure du Projet

```
document-ia-api/
├── src/
│   ├── __init__.py
│   ├── main.py                      # Point d'entrée FastAPI
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py               # Configuration avec variable d'env API_KEY
│   │   ├── auth.py                 # Authentification API_KEY
│   │   └── exceptions/             # Gestion des exceptions HTTP
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py               # Routes API
│   ├── middleware/                  # Middleware FastAPI
│   ├── models/                     # Modèles de données
│   └── schemas/                    # Schémas Pydantic
├── tests/                          # Tests unitaires et d'intégration
├── pyproject.toml                  # Configuration Poetry
└── poetry.lock                     # Verrouillage des dépendances
```

## Installation

1. **Installer Poetry** (si pas déjà installé)
```bash
pipx install poetry
```

2. **Installer les dépendances**
```bash
poetry install
```

3. **Configurer l'environnement**
```bash
cp env.example .env
# Éditer .env et définir votre API_KEY
```

## Utilisation

### Démarrage en mode développement
```bash
poetry run dev
```

### Démarrage en mode production
```bash
poetry run start
```

## Endpoints

- **GET /** - Page d'accueil avec liens vers la documentation
- **GET /api/v1/** - Statut de l'API (authentification requise)
- **GET /api/health** - Vérification de santé (authentification requise)
- **GET /docs** - Documentation Swagger UI
- **GET /redoc** - Documentation ReDoc
- **GET /openapi.json** - Spécification OpenAPI

## Authentification

Tous les endpoints `/api/*` nécessitent une authentification via l'en-tête `X-API-KEY` :

```bash
curl -H "X-API-KEY: YOUR_API_KEY" http://localhost:8000/api/v1/
```

**Note**: L'authentification utilise l'en-tête `X-API-KEY` et non le schéma Bearer token.

## Variables d'Environnement

- `API_KEY` : Clé d'authentification requise
- `HOST` : Hôte du serveur (défaut: 0.0.0.0)
- `PORT` : Port du serveur (défaut: 8000)

## Dépendances Principales

- **FastAPI** : Framework web moderne et rapide
- **Uvicorn** : Serveur ASGI pour FastAPI
- **SQLAlchemy** : ORM pour la gestion des bases de données
- **Pydantic** : Validation des données et sérialisation
- **Pydantic-settings** : Gestion des paramètres de configuration

## Développement

Le projet utilise Poetry pour la gestion des dépendances et inclut :
- Configuration automatique de CORS
- Gestion des exceptions HTTP personnalisées
- Structure modulaire pour faciliter l'extension
- Tests unitaires (structure en place)

## Déploiement

Le projet est configuré pour être déployé sur Scalingo (Heroku like) en production.