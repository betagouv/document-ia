import base64
import logging

import httpx
from pydantic import BaseModel

from document_ia_worker.core.ocr.base_http_ocr_service import BaseHttpOCRService
from document_ia_worker.core.ocr.mistral.mistral_ocr_response import MistralOcrResponse
from document_ia_worker.core.ocr.mistral.mistral_ocr_settings import (
    MistralOcrSettings,
    mistral_ocr_settings,
)
from document_ia_worker.core.ocr.ocr_result import HttpOcrResult
from document_ia_worker.exception.http_ocr_miss_configuration_exception import (
    HTTPOCRMissConfigurationException,
)

logger = logging.getLogger(__name__)


class MistralOcrResult(BaseModel):
    success: bool
    content: str


class MistralHttpOcrService(BaseHttpOCRService[MistralOcrSettings]):
    def __init__(
        self,
        config: MistralOcrSettings = mistral_ocr_settings,
        timeout: int = 60,
        connection_timeout: int = 60,
    ):
        super().__init__(config, timeout, connection_timeout)

    async def make_request(
        self, client: httpx.AsyncClient, file_path: str, mime_type: str
    ) -> httpx.Response:
        with open(file_path, "rb") as f:
            raw_bytes = f.read()
        b64_content = base64.b64encode(raw_bytes).decode("ascii")

        # Construction de l'URL data, en utilisant le mime_type fourni
        data_url = f"data:{mime_type};base64,{b64_content}"

        if mime_type.startswith("image/"):
            document_content = {
                "type": "image_url",
                "image_url": data_url,
            }
        else:
            document_content = {
                "type": "document_url",
                "document_url": data_url,
            }

        payload = {
            "model": "mistral-ocr-2512",
            "document": document_content,
        }

        timeout = httpx.Timeout(self.timeout, connect=self.connection_timeout)
        headers = {
            "Authorization": f"Bearer {self.get_api_key()}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(
                f"{self.get_base_url()}/ocr", headers=headers, json=payload
            )

    def parse_response(self, response: httpx.Response) -> HttpOcrResult:
        response.raise_for_status()

        mistral_result = MistralOcrResponse.model_validate_json(response.text)
        returned_content = ""

        for page in mistral_result.pages:
            returned_content += f"Page : {page.index} \n {page.markdown} \n"

        return HttpOcrResult(success=True, content=returned_content)

    def get_api_key(self) -> str:
        if self.config.MISTRAL_OCR_API_KEY is None:
            raise HTTPOCRMissConfigurationException("Mistral")
        return self.config.MISTRAL_OCR_API_KEY.get_secret_value()

    def get_base_url(self) -> str:
        if self.config.MISTRAL_ORC_BASE_URL is None:
            raise HTTPOCRMissConfigurationException("Mistral")
        return self.config.MISTRAL_ORC_BASE_URL
