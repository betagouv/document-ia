TODO:
- utiliser les `json_schema_extra` pour savoir quelle metrique utiliser
https://github.com/betagouv/document-ia/blob/ddc3f4e3805070086792e0ab7324e98b18d4a988/document-ia-schemas/src/document_ia_schemas/avis_imposition.py

Creer une enum : Metrics: {
    equality: "equality"
} dans document-ia-schemas pour qu'on puisse l'utiliser a la place de https://github.com/betagouv/document-ia/blob/ddc3f4e3805070086792e0ab7324e98b18d4a988/document-ia-schemas/src/document_ia_schemas/avis_imposition.py#L15

- lancer les experiments plusieurs fois pour avoir l'ecart type

- trouver le moyen de reconstruire raw document-ai api  response (ou de s'en passer) dans document-ia-evals/pages/5_🔧_Create_Dataset.py, car quand on change les champs texte dans label studio, ca mets pas a jour le champs raw document-ai api response

- prevoir de pouvoir lancer des evals a une certaine date (la nuit)

- constituer vrai dataset de ground truth avec Avis d'imposition.

- pour la creation d'un dataset ground truth, on sait le schema qu'on veut. Donc on veut skip la partie classification de document-ia.
Pour faire ca : utiliser workflow "fast" (ie: document-extraction-fast-marker-v1) avec en meta le document-type ex: {"document-type": "cni"} 
Aussi: peut-on stocker le SupportedDocumentType (cni,...) dans une metadata du projet label studio? 