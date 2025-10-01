
# TODO

- FastAPI OpenAPI documentation
  - Plus finement comprendre son fonctionnement et corriger la documentation (notamment les status code d'erreur)
- Schéma des events (afin de pouvoir plus facilement anonymiser les logs, cela serait plus simple d'avoir un sous-objet $event aux schéma d'event, ex: WorkflowExecutionStartedEvent)
- Créer un service de log qui gère l'anonymisation des propriétés avec des PPI
- La logique de retry de connexion du Service Redis ne fonctionne pas encore correctement (voir fichier redis_service.py)
- Créer des exceptions HTTP pour les status code classique (400 BadRequest, 404 NotFound, 429 Too Many Requests etc). Supprimer la dépendance $fastcrud
- Faire en sorte que l'exécution d'un workflow soit déclenché **si et seulement si** les 3 actions suivantes sont un succès :
  - publication event redis,
  - dépot fichier S3,
  - persistance eventStore postgres
  -> sinon rollback les actions
- Il y a probablement un refacto de la logique de rate limiting dans le service redis à faire. On pourrait isoler et tester la logique métier (calcul des boundaries pour les fixed windows)
- Se mettre d'accord sur les conventions de naming et langues de commentaires (anglais si vocation à créer une brique open-source, sauf vocable spécifique fr admin ou financier, ex: "revenu fiscal de reference")
- Revoir la création de l'app pour partager la configuration entre les tests et le main.py
- [WORKER - LLM] remonté les infos de consommation (tokens) dans les requêtes llm
- Stocker le temps d'éxecution de chaques steps. (uniquement logs)
# RAF
- Mettre sentry
- Supprimer les fichiers S3 après l'éxecution
- Anonymisation des entrées en db.
- Mise en oeuvre de la brique OCR (dans un premier temps simple librairie), prévoir de pouvoir choisir la brique OCR (Tesseract, easy-OCR, HTTPMarker)
- Mise en oeuvre des schémas, prompts et du service de classification (reprendre le code https://github.com/MTES-MCT/dossierfacile-ocr-extractor)
- Mise en oeuvre des schémas, prompts et du service d'extraction
- Les 3 actions OCR, classification et extraction peuvent avoir lieu dans une même exécution (pas la peine mettre en oeuvre des events et workers/consumers intermédiaires)
- Remarque : toutes le configuration doit être portée dans le fichier workflows.json (qui mock le résultat d'un appel API sur la console d'admin)
  - Il serait de bon gout d'avoir un système de cache pour limiter l'accès à ce fichier
- Idem le (ou les) fichier **-schema.json mock le résultat d'appel API sur la console d'admin
- Mise en oeuvre logique de webhook (pas de retry dans un premier temps)
