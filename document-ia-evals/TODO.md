TODO:
- [x] utiliser les `json_schema_extra` pour savoir quelle metrique utiliser
- [x] trouver le moyen de reconstruire raw document-ai api  response (ou de s'en passer) dans document-ia-evals/pages/5_🔧_Create_Dataset.py, car quand on change les champs texte dans label studio, ca mets pas a jour le champs raw document-ai api response
- [x] pour la creation d'un dataset ground truth, on sait le schema qu'on veut. Donc on veut skip la partie classification de document-ia.
Pour faire ca : utiliser workflow "fast" (ie: document-extraction-fast-marker-v1) avec en meta le document-type ex: {"document-type": "cni"} 
Aussi: peut-on stocker le SupportedDocumentType (cni,...) dans une metadata du projet label studio? 
- [x] Evals: sauvegarder temps de traitement de chaque appel -> moyenne ecart type 

- [ ] constituer vrai dataset de ground truth avec Avis d'imposition.
- [ ] constituer vrai dataset de ground truth avec CNI.
- [ ] mettre declarant 2 dans avis_imposition.py

- [ ] prevoir de pouvoir lancer des evals a une certaine date (la nuit)
- [ ] lancer les experiments plusieurs fois pour avoir l'ecart type