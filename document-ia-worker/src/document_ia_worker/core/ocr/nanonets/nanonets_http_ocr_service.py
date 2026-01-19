from document_ia_worker.core.ocr.base_http_ocr_service import BaseHttpOCRService
from document_ia_worker.core.ocr.nanonets.nanonets_settings import (
    NanonetsSettings,
    nanonets_settings,
)
from document_ia_worker.exception.http_ocr_miss_configuration_exception import (
    HTTPOCRMissConfigurationException,
)


class NanonetsHttpHttpOcrService(BaseHttpOCRService[NanonetsSettings]):
    def __init__(
        self,
        config: NanonetsSettings = nanonets_settings,
        timeout: int = 60,
        connection_timeout: int = 60,
    ):
        super().__init__(config, timeout, connection_timeout)

    def get_api_key(self) -> str:
        if self.config.NANONETS_API_KEY is None:
            raise HTTPOCRMissConfigurationException("Nanonets")
        return self.config.NANONETS_API_KEY.get_secret_value()

    def get_base_url(self) -> str:
        if self.config.NANONETS_BASE_URL is None:
            raise HTTPOCRMissConfigurationException("Nanonets")
        return self.config.NANONETS_BASE_URL
