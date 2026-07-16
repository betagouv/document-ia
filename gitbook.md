# DocumentIA, votre pipeline d'analyse documentaire

### Contexte et présentation du projet

#### Bénéfices et cas d'usage

Une solution d'intelligence documentaire permet notamment :

| Cas d'usage                          | Bénéfices                                                                                                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Retour direct à l'usager**         | Satisfaction usager, qualité des dossiers en instruction, diminution des coûts. L'usager peut corriger son dossier immédiatement, sans attendre l'instructeur |
| **Automatisation de l'instruction**  | Réduction des coûts et délais, amélioration de l'expérience utilisateur. Passage d'une analyse manuelle à une extraction automatisée des données              |
| **Lutte contre la fraude**           | Assistance des agents, détection améliorée grâce au croisement de sources de données                                                                          |
| **Constitution de bases de données** | Numérisation et analyse de documents historiques, patrimoniaux ou non structurés                                                                              |

<a href="https://beta.gouv.fr/startups/document-ia.html" class="button primary">Voir la page produit beta.gouv.fr</a>

#### Guide de mise en œuvre

Un **guide plus complet** sur la mise en œuvre de solutions d'intelligence documentaire est disponible. Il couvre notamment l'investigation métier et technique, le prototypage, l'évaluation des performances, les enjeux juridiques et les bonnes pratiques pour les administrations.\
→ Consultez le Guide Intelligence Documentaire pour une approche globale.

***

### Introduction technique

Document-IA est une solution **générique, souveraine** et **sécurisée** d’**analyse automatique** de pièces justificatives, disponible par API.

L’API Document-IA déploie les fonctionnalités principales suivantes :

* **Catégorisation** du type de document
* **Extraction** des informations présentes dans le document sous un format standardisé
* **Identification** et lecture de **codes à barres** : QRcode, 2DDOC

### Concepts clés

#### Workflow

Un **workflow** est une **pipeline de traitement de document** qui décrit **quelles sont les étapes à réaliser et dans quel ordre.** Dans un workflow, on peut préciser des règles : quels sont les types de fichiers supportés, quel modèle OCR ou LLM utiliser etc.

Chaque étape est une **brique atomique** du workflow : une étape de traitement (ex: télécharger, pré-traiter, extraire le texte via OCR, extraire les informations via LLM, sauvegarder les résultats).

Liste de tous les **workflows disponibles** en environnement de sandbox :

🔗 <https://github.com/betagouv/document-ia/blob/sandbox/document-ia-infra/src/document_ia_infra/data/workflow/data/workflows.json>

#### Schéma

Un **schéma de document** décrit **quelles informations sont attendues** pour un type de document donné, et **comment elles doivent être nommées et structurées**. C’est la définition typée des données à extraire pour un type de pièce (CNI, passeport, avis d’imposition, etc.).

* Exemple (carte d’identité) : prénom, nom, date de naissance, numéro de document, etc.

Liste complète des **schémas disponibles** en environnement de sandbox :

🔗 <https://github.com/betagouv/document-ia/tree/sandbox/document-ia-schemas/src/document_ia_schemas>

***

### Environnement (Sandbox)

**URL de base :** `https://api.sandbox.document-ia.beta.gouv.fr`

### Authentification

L'API utilise une authentification par clé API (token). Vous devez inclure votre clé dans l'en-tête de vos requêtes HTTP avec le header `X-API-KEY`

{% hint style="info" icon="lightbulb" %}
Pour disposer d’une clé d’API, vous devez contacter l’équipe Document-IA
{% endhint %}

***

### Ressources

#### Documentation API

Pour plus de détails sur les paramètres et les réponses, consultez la documentation :

🔗 [https://api.sandbox.document-ia.beta.gouv.fr/redoc](https://api.sandbox.document-ia.beta.gouv.fr/redoc#tag/Workflows/operation/execute_workflow_sync_api_v1_workflows__workflow_id__execute_sync_post)

#### Collection API

Une collection [Bruno](https://www.usebruno.com/) est disponible pour tester l'API facilement

🔗 <https://github.com/betagouv/document-ia/tree/sandbox/document-ia-api/bruno-api>

***

### Appel API synchrone

Il est possible d’appeler l’API de 2 manières :

* **synchrone** via la route `POST /api/v1/workflows/{workflow_id}/execute`, le résultat de l’exécution est dans ce cas directement disponible dans la réponse de la requête.
* **asynchrone** via la `POST /api/v1/workflows/{workflow_id}/execute_sync`, le endpoint répond avec un id d’exécution `execution_id`, le résultat de l’exécution peut être récupéré alors par :
  * appel API, pulling sur la route `GET /api/v1/executions/{{execution_id}}`
  * par webhook sur l’url de votre choix (contacter l’équipe Document-IA pour la configuration du webhook)

### Workflow spécifique : Extraction de codes-barres

Pour l'extraction de codes-barres 2D-DOC sans analyse par LLM, utilisez le workflow :

**`document-barcode-extraction`**

Ce workflow :

* N'utilise pas de LLM
* N'utilise pas d'OCR
* Extrait directement les codes-barres des documents et vérifie les signatures 2DDOC.

{% hint style="info" icon="lightbulb" %}
L’utilisation de ce workflow dans le cadre d’appel API synchrone est recommandé (faible latence : \~500ms).
{% endhint %}
