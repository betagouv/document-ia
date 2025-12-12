import logging
import os
from json import JSONDecodeError

import httpx
from pydantic import BaseModel

from document_ia_worker.core.deepseek_ocr.deepseek_ocr_settings import deepseek_ocr_settings

logger = logging.getLogger(__name__)


class DeepseekOcrResult(BaseModel):
    success: bool
    content: str


class DeepseekOcrService:
    def __init__(self) -> None:
        if deepseek_ocr_settings.DEEPSEEK_OCR_API_KEY is not None:
            self.api_key = deepseek_ocr_settings.DEEPSEEK_OCR_API_KEY.get_secret_value()

        if deepseek_ocr_settings.DEEPSEEK_OCR_BASE_URL is not None:
            self.base_url = deepseek_ocr_settings.DEEPSEEK_OCR_BASE_URL

    async def extract_text_from_image(self, file_path: str) -> DeepseekOcrResult:
        """Envoie un fichier à l'API Deepseek OCR pour extraction en markdown.

        Args:
            file_path: chemin local du fichier (image/PDF) à envoyer.

        Returns:
            DeepseekOcrResult: résultat structuré contenant le markdown ou l'erreur.
        """
        if not os.path.exists(file_path):
            return DeepseekOcrResult(
                success=False,
                content="",
            )
        if not self.api_key:
            return DeepseekOcrResult(success=False, content="")

        logger.info(f"Appel Deepseek OCR url: {self.base_url} fichier={file_path}")

        try:
            timeout = httpx.Timeout(180.0, connect=10.0)
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
            return DeepseekOcrResult(
                success=True,
                content=parsed,
            )
        except httpx.RequestError as e:
            logger.error(f"Erreur réseau Deepseek OCR: {e}")
            return DeepseekOcrResult(
                success=False,
                content="",
            )
        except JSONDecodeError as e:
            logger.error(f"Erreur parsing JSON Deepseek OCR: {e}")
            return DeepseekOcrResult(
                success=False,
                content="",
            )
        except Exception:
            logger.exception("Exception inattendue lors de l'appel Deepseek OCR")
            return DeepseekOcrResult(
                success=False,
                content="",
            )