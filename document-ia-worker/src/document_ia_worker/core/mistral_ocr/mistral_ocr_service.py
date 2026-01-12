import logging
import os
import base64
from json import JSONDecodeError

import httpx
from pydantic import BaseModel

from document_ia_worker.core.mistral_ocr.mistral_ocr_response import MistralOcrResponse
from document_ia_worker.core.mistral_ocr.mistral_ocr_settings import (
    mistral_ocr_settings,
)

logger = logging.getLogger(__name__)


class MistralOcrResult(BaseModel):
    success: bool
    content: str


class MistralOcrService:
    def __init__(self) -> None:
        if mistral_ocr_settings.MISTRAL_OCR_API_KEY is not None:
            self.api_key = mistral_ocr_settings.MISTRAL_OCR_API_KEY.get_secret_value()
        else:
            self.api_key = None

        if mistral_ocr_settings.MISTRAL_ORC_BASE_URL is not None:
            self.base_url = mistral_ocr_settings.MISTRAL_ORC_BASE_URL
        else:
            self.base_url = None

    async def extract_text_from_image(
        self, file_path: str, mime_type: str
    ) -> MistralOcrResult:
        """Envoie un fichier à l'API Mistral OCR pour extraction en markdown.

        Args:
            file_path: chemin local du fichier (image/PDF) à envoyer.
            mime_type: mime type du fichier (ex: "application/pdf", "image/png").

        Returns:
            MistralOcrResult: résultat structuré contenant le markdown ou l'erreur.
        """
        if not os.path.exists(file_path):
            logger.error("Fichier introuvable pour Mistral OCR: %s", file_path)
            return MistralOcrResult(success=False, content="")

        if not self.api_key or not self.base_url:
            logger.error(
                "Configuration Mistral OCR incomplète (api_key/base_url manquants)"
            )
            return MistralOcrResult(success=False, content="")

        logger.info("Appel Mistral OCR url: %s fichier=%s", self.base_url, file_path)

        try:
            # Lecture et encodage base64 du fichier
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
            b64_content = base64.b64encode(raw_bytes).decode("ascii")

            # Construction de l'URL data, en utilisant le mime_type fourni
            data_url = f"data:{mime_type};base64,{b64_content}"

            payload = {
                "model": "mistral-ocr-2505",
                "document": {
                    "type": "document_url",
                    "document_url": data_url,
                },
            }

            timeout = httpx.Timeout(60.0, connect=10.0)
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.base_url}/ocr", headers=headers, json=payload
                )

            response.raise_for_status()

            mistral_result = MistralOcrResponse.model_validate_json(response.text)
            returned_content = ""

            for page in mistral_result.pages:
                returned_content += f"Page : {page.index} \n {page.markdown} \n"

            return MistralOcrResult(success=True, content=returned_content)

        except httpx.HTTPStatusError as e:
            logger.error("Erreur HTTP Mistral OCR (%s): %s", e.response.status_code, e)
            return MistralOcrResult(success=False, content="")
        except httpx.RequestError as e:
            logger.error("Erreur réseau Mistral OCR: %s", e)
            return MistralOcrResult(success=False, content="")
        except JSONDecodeError as e:
            logger.error("Erreur parsing JSON Mistral OCR: %s", e)
            return MistralOcrResult(success=False, content="")
        except Exception:
            logger.exception("Exception inattendue lors de l'appel Mistral OCR")
            return MistralOcrResult(success=False, content="")
