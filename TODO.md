
# TODO

- FastAPI OpenAPI documentation
  - Plus finement comprendre son fonctionnement et corriger la documentation (notamment les status code d'erreur)
- La logique de retry de connexion du Service Redis ne fonctionne pas encore correctement (voir fichier redis_service.py)
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
- Anonymisation des entrées en db.
- Remarque : toutes le configuration doit être portée dans le fichier workflows.json (qui mock le résultat d'un appel API sur la console d'admin)
  - Il serait de bon gout d'avoir un système de cache pour limiter l'accès à ce fichier
- Idem le (ou les) fichier **-schema.json mock le résultat d'appel API sur la console d'admin
- Mise en oeuvre logique de webhook (pas de retry dans un premier temps)
