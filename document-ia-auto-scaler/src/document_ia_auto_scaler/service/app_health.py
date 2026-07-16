import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class AppHealthService:
    """
    Service chargé de récupérer les métriques d'état de l'application
    et en particulier le retard de traitement (lag) dans Redis.
    """

    def __init__(self, health_url: str):
        self.health_url = health_url

    def get_queue_lag(self) -> int | None:
        """
        Interroge le endpoint de health check de l'API pour lire le backlog Redis.
        Returns:
            int: Le retard de la queue (nb_execution_undelivered),
                 ou None en cas d'erreur de communication.
        """
        req = urllib.request.Request(
            self.health_url,
            method="GET",
            headers={"Accept": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                redis_status = data.get("redis", {})
                lag = redis_status.get("nb_execution_undelivered")

                if lag is not None:
                    return int(lag)
                else:
                    logger.warning(
                        "La clé 'nb_execution_undelivered' est absente du health check."
                    )
                    return 0
        except urllib.error.HTTPError as e:
            # En cas de 503 Service Unavailable, l'API renvoie des détails d'erreur.
            # On tente de parser le JSON d'erreur pour y trouver la métrique de lag de la queue.
            try:
                data = json.loads(e.read().decode("utf-8"))
                errors = data.get("errors", {})
                redis_status = errors.get("redis", {})
                lag = redis_status.get("nb_execution_undelivered")
                if lag is not None:
                    return int(lag)
            except Exception:
                pass
            logger.error("Erreur HTTP %d lors de l'appel au healthcheck API.", e.code)
            return None
        except Exception as e:
            logger.error("Impossible de joindre le healthcheck de l'API : %s", e)
            return None
