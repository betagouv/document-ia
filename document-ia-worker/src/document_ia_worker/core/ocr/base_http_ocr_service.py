import logging
import os
from abc import ABC, abstractmethod
from typing import TypeVar

import httpx

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings
from document_ia_infra.core.ocr_type import OCRType
from document_ia_worker.core.ocr.ocr_result import HttpOcrResult

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

        except Exception as e:
            logger.error(f"Unexpected error during HTTP OCR call: {e}")
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

    @abstractmethod
    def get_api_key(self) -> str:
        raise NotImplementedError("Subclasses must implement get_api_key method")

    @abstractmethod
    def get_base_url(self) -> str:
        raise NotImplementedError("Subclasses must implement get_base_url method")

    @abstractmethod
    def get_ocr_type(self) -> OCRType:
        raise NotImplementedError("Subclasses must implement get_ocr_type method")
