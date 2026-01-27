class HTTPOCRMissConfigurationException(Exception):
    def __init__(self, ocr_service_name: str):
        self.ocr_service_name = ocr_service_name
        super().__init__(f"Ocr Service {ocr_service_name} miss configuration")
