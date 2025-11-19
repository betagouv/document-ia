import logging
import os
from json import JSONDecodeError

import httpx
from pydantic import BaseModel

from document_ia_worker.core.nanonets.nanonets_settings import nanonets_settings

logger = logging.getLogger(__name__)


class NanonetsOcrResult(BaseModel):
    success: bool
    content: str


class NanonetsService:
    def __init__(self) -> None:
        if nanonets_settings.NANONETS_API_KEY is not None:
            self.api_key = nanonets_settings.NANONETS_API_KEY.get_secret_value()

        if nanonets_settings.NANONETS_BASE_URL is not None:
            self.base_url = nanonets_settings.NANONETS_BASE_URL

    async def extract_text_from_image(self, file_path: str) -> NanonetsOcrResult:
        """Envoie un fichier à l'API Nanonets pour extraction en markdown.

        Args:
            file_path: chemin local du fichier (image/PDF) à envoyer.

        Returns:
            NanonetsOcrResult: résultat structuré contenant le markdown ou l'erreur.
        """
        if not os.path.exists(file_path):
            return NanonetsOcrResult(
                success=False,
                content="",
            )
        if not self.api_key:
            return NanonetsOcrResult(success=False, content="")

        logger.info(f"Appel Nanonets url: {self.base_url} fichier={file_path}")

        try:
            timeout = httpx.Timeout(30.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                with open(file_path, "rb") as f:
                    files = {
                        "file": (
                            os.path.basename(file_path),
                            f,
                            "application/octet-stream",
                        )
                    }
                    headers = {"x-api-key": self.api_key}
                    response = await client.post(
                        self.base_url, headers=headers, files=files
                    )
            parsed: str = response.json()["text"]
            return NanonetsOcrResult(
                success=True,
                content=parsed,
            )
        except httpx.RequestError as e:
            logger.error(f"Erreur réseau Nanonets: {e}")
            return NanonetsOcrResult(
                success=False,
                content="",
            )
        except JSONDecodeError as e:
            logger.error(f"Erreur parsing JSON Nanonets: {e}")
            return NanonetsOcrResult(
                success=False,
                content="",
            )
        except Exception:
            logger.exception("Exception inattendue lors de l'appel Nanonets")
            return NanonetsOcrResult(
                success=False,
                content="",
            )