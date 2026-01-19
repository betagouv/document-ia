import logging
import os
from abc import ABC
from json import JSONDecodeError
from typing import TypeVar

import httpx

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings
from document_ia_worker.core.ocr.ocr_result import HttpOcrResult
from document_ia_worker.exception.http_ocr_miss_configuration_exception import (
    HTTPOCRMissConfigurationException,
)

C = TypeVar("C", bound=BaseDocumentIaSettings)

logger = logging.getLogger(__name__)


class BaseHttpOCRService[C](ABC):
    def __init__(self, config: C, timeout: int = 60, connection_timeout: int = 60):
        self.config = config
        self.timeout = timeout
        self.connection_timeout = connection_timeout

    async def extract_text_from_image(
        self, file_path: str, mime_type: str
    ) -> HttpOcrResult:
        if not os.path.exists(file_path):
            return HttpOcrResult(
                success=False,
                content="",
            )

        try:
            timeout = httpx.Timeout(self.timeout, connect=self.connection_timeout)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await self.make_request(client, file_path, mime_type)
                return self.parse_response(response)

        except HTTPOCRMissConfigurationException as e:
            logger.error(f"{e}")
            return HttpOcrResult(
                success=False,
                content="",
            )
        except httpx.TimeoutException as e:
            logger.error(f"Timeout lors de l'appel OCR HTTP: {e}")
            return HttpOcrResult(
                success=False,
                content="",
            )
        except httpx.RequestError as e:
            logger.error(f"Erreur appel OCR: {e}")
            return HttpOcrResult(
                success=False,
                content="",
            )
        except JSONDecodeError as e:
            logger.error(f"Erreur parsing JSON OCR: {e}")
            return HttpOcrResult(
                success=False,
                content="",
            )
        except Exception:
            logger.exception("Exception inattendue lors de l'appel http OCR")
            return HttpOcrResult(
                success=False,
                content="",
            )

    async def make_request(
        self, client: httpx.AsyncClient, file_path: str, mime_type: str
    ) -> httpx.Response:
        with open(file_path, "rb") as f:
            files = {
                "file": (
                    os.path.basename(file_path),
                    f,
                    "application/octet-stream",
                )
            }
            headers = {"x-api-key": self.get_api_key()}
            return await client.post(self.get_base_url(), headers=headers, files=files)

    def parse_response(self, response: httpx.Response) -> HttpOcrResult:
        if response.status_code == 200:
            parsed: str = response.json()["text"]
            return HttpOcrResult(
                success=True,
                content=parsed,
            )
        else:
            return HttpOcrResult(
                success=False,
                content="",
            )

    def get_api_key(self) -> str:
        raise NotImplementedError("Subclasses must implement get_api_key method")

    def get_base_url(self) -> str:
        raise NotImplementedError("Subclasses must implement get_base_url method")
