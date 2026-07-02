import base64
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from pydantic import SecretStr

logger = logging.getLogger(__name__)


class ScalingoService:
    """
    Service encapsulant toutes les interactions avec l'API de Scalingo.
    Gère de façon autonome l'authentification et le cycle de vie du token Bearer.
    """

    def __init__(
            self,
            api_token: SecretStr,
            app_name: str,
            api_url: str,
            auth_url: str,
    ):
        self.api_token = api_token
        self.app_name = app_name
        self.api_url = api_url.rstrip("/")
        self.auth_url = auth_url.rstrip("/")

        # État interne d'authentification
        self._cached_token: str | None = None
        self._token_expiration_time: float = 0.0

    def _get_bearer_token(self) -> str:
        """
        Échange le token d'API permanent contre un token Bearer temporaire (1h).
        Utilise un cache local pour limiter les appels réseau redondants.
        """
        now = time.time()
        token = self._cached_token
        # Réutilisation du token s'il est encore valide pour plus de 5 minutes
        if token and now < (self._token_expiration_time - 300):
            return token

        token_str = self.api_token.get_secret_value()
        logger.info("Renouvellement du Bearer token auprès de Scalingo Auth...")

        try:
            auth_str = f":{token_str}"
            auth_bytes = auth_str.encode("utf-8")
            auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")

            req = urllib.request.Request(
                f"{self.auth_url}/v1/tokens/exchange",
                method="POST",
                headers={
                    "Authorization": f"Basic {auth_b64}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                new_token = str(res_data["token"])
                self._cached_token = new_token
                self._token_expiration_time = now + 3600
                logger.info("Bearer token obtenu avec succès.")
                return new_token

        except Exception as e:
            logger.error("Échec de l'obtention du Bearer token : %s", e)
            fallback = self._cached_token
            if fallback:
                logger.info("Utilisation du token expiré en mode fallback.")
                return fallback
            raise

    def _send_request(
            self, url_path: str, method: str = "GET", payload: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """
        Méthode générique interne d'envoi de requêtes authentifiées à l'API Scalingo.
        Centralise l'injection d'en-têtes et le traitement d'erreurs.
        """
        try:
            bearer_token = self._get_bearer_token()
            url = f"{self.api_url}{url_path}"

            headers = {
                "Authorization": f"Bearer {bearer_token}",
                "Accept": "application/json",
            }

            data_bytes = None
            if payload is not None:
                data_bytes = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"

            req = urllib.request.Request(
                url,
                data=data_bytes,
                method=method,
                headers=headers,
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                body = response.read().decode("utf-8")
                if not body:
                    return {}
                res_json: Any = json.loads(body)
                if isinstance(res_json, dict):
                    return res_json
                return {"data": res_json}

        except urllib.error.HTTPError as e:
            logger.error(
                "Erreur HTTP lors de la requête %s %s : %d - %s",
                method,
                url_path,
                e.code,
                e.read().decode("utf-8"),
            )
            return None
        except Exception as e:
            logger.error(
                "Erreur de communication API vers %s %s : %s",
                method,
                url_path,
                e,
            )
            return None

    def get_number_workers(self) -> int | None:
        """
        Récupère le nombre de conteneurs de type 'worker' actuellement actifs.
        Returns:
            int: Le nombre de workers actifs, ou None en cas d'erreur de communication.
        """
        result = self._send_request(f"/v1/apps/{self.app_name}/ps")
        if result is None:
            return None

        containers = result.get("containers", [])
        if not isinstance(containers, list):
            logger.error("Format inattendu de la réponse Scalingo (containers n'est pas une liste).")
            return None

        containers_list = containers
        workers: list[dict[str, Any]] = []
        for c in containers_list:
            if isinstance(c, dict):
                if c.get("type") == "worker":
                    workers.append(c)
        return len(workers)

    def scale_workers(self, new_amount: int) -> bool:
        """
        Ajuste le nombre de conteneurs de type 'worker'.
        Args:
            new_amount (int): Le nombre cible de conteneurs workers.
        Returns:
            bool: True si la demande a été acceptée par Scalingo, False sinon.
        """
        payload = {
            "containers": [
                {
                    "name": "worker",
                    "amount": new_amount,
                }
            ]
        }
        # Scalingo API scale endpoint retourne un status 200 ou 202 en cas de succès.
        # Comme _send_request retourne None en cas d'erreur, tout retour non-None indique le succès.
        result = self._send_request(
            f"/v1/apps/{self.app_name}/scale", method="POST", payload=payload
        )
        return result is not None
