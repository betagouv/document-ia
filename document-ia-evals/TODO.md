TODO:
- run annotation pipeline with worflow id and dataset

- utiliser les `json_schema_extra` pour savoir quelle metrique utiliser
https://github.com/betagouv/document-ia/blob/ddc3f4e3805070086792e0ab7324e98b18d4a988/document-ia-schemas/src/document_ia_schemas/avis_imposition.py

Creer une enum : Metrics: {
    equality: "equality"
} dans document-ia-schemas pour qu'on puisse l'utiliser a la place de https://github.com/betagouv/document-ia/blob/ddc3f4e3805070086792e0ab7324e98b18d4a988/document-ia-schemas/src/document_ia_schemas/avis_imposition.py#L15

- lancer les experiments plusieurs fois pour avoir l'ecart type