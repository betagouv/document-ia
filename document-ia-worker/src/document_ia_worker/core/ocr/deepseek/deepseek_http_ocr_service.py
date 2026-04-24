from document_ia_infra.core.ocr_type import OCRType
from document_ia_worker.core.ocr.base_http_ocr_service import BaseHttpOCRService
from document_ia_worker.core.ocr.deepseek.deepseek_ocr_settings import (
    DeepseekOCRSettings,
    deepseek_ocr_settings,
)
from document_ia_worker.exception.http_ocr_miss_configuration_exception import (
    HTTPOCRMissConfigurationException,
)


class DeepSeekHttpHttpOcrService(BaseHttpOCRService[DeepseekOCRSettings]):
    def __init__(
        self,
        config: DeepseekOCRSettings = deepseek_ocr_settings,
        timeout: int = 60,
        connection_timeout: int = 60,
    ):
        super().__init__(config, timeout, connection_timeout)

    def get_api_key(self) -> str:
        if self.config.DEEPSEEK_OCR_API_KEY is None:
            raise HTTPOCRMissConfigurationException("Deepseek")
        return self.config.DEEPSEEK_OCR_API_KEY.get_secret_value()

    def get_base_url(self) -> str:
        if self.config.DEEPSEEK_OCR_BASE_URL is None:
            raise HTTPOCRMissConfigurationException("Deepseek")
        return self.config.DEEPSEEK_OCR_BASE_URL

    def get_ocr_type(self) -> OCRType:
        return OCRType.DEEPSEEK
