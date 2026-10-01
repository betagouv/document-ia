from enum import Enum


class LLMModel(str, Enum):
    ALBERT_SMALL = "albert-small"
    OPEN_WEIGHT_LARGE = "openweight-large"
    OPEN_WEIGHT_MEDIUM = "openweight-medium"
    OPEN_WEIGHT_SMALL = "openweight-small"
    MISTRAL_MEDIUM = "mistral-medium-2508"


class VLMModel(str, Enum):
    MISTRAL_MEDIUM_3_5 = "mistral-medium-3-5"


class OCRModel(str, Enum):
    TESSERACT = "tesseract"
    MISTRAL = "mistral"
    LIGHT_ON = "lightOn"


class BarcodeExtractionType(str, Enum):
    TWO_D_DOC = "2ddoc"
    RAW = "raw"
