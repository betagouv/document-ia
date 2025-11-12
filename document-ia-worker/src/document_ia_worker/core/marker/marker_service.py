import logging
import os
from json import JSONDecodeError

import httpx
from pydantic import BaseModel

from document_ia_worker.core.marker.marker_settings import marker_settings

logger = logging.getLogger(__name__)


class MarkerOcrResult(BaseModel):
    success: bool
    content: str


class MarkerService:
    def __init__(self) -> None:
        if marker_settings.MARKER_API_KEY is not None:
            self.api_key = marker_settings.MARKER_API_KEY.get_secret_value()

        if marker_settings.MARKER_BASE_URL is not None:
            self.base_url = marker_settings.MARKER_BASE_URL

    async def extract_text_from_image(self, file_path: str) -> MarkerOcrResult:
        """Envoie un fichier à l'API Albert pour extraction en markdown.

        Args:
            file_path: chemin local du fichier (image/PDF) à envoyer.

        Returns:
            AlbertExtractionResult: résultat structuré contenant le markdown ou l'erreur.
        """
        if not os.path.exists(file_path):
            return MarkerOcrResult(
                success=False,
                content="",
            )
        if not self.api_key:
            return MarkerOcrResult(success=False, content="")

        logger.info(f"Appel Marker url: {self.base_url} fichier={file_path}")

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
            return MarkerOcrResult(
                success=True,
                content=parsed,
            )
        except httpx.RequestError as e:
            logger.error(f"Erreur réseau Marker: {e}")
            return MarkerOcrResult(
                success=False,
                content="",
            )
        except JSONDecodeError as e:
            logger.error(f"Erreur parsing JSON Marker: {e}")
            return MarkerOcrResult(
                success=False,
                content="",
            )
        except Exception:
            logger.exception("Exception inattendue lors de l'appel Marker")
            return MarkerOcrResult(
                success=False,
                content="",
            )
