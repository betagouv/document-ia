from enum import Enum


class LLMModel(str, Enum):
    ALBERT_LARGE = "albert-large"
    ALBERT_SMALL = "albert-small"
    OPEN_WEIGHT_LARGE = "openweight-large"
    OPEN_WEIGHT_SMALL = "openweight-small"
    MISTRAL_MEDIUM = "mistral-medium-2508"


class OCRModel(str, Enum):
    TESSERACT = "tesseract"
    MISTRAL = "mistral"


class BarcodeExtractionType(str, Enum):
    TWO_D_DOC = "2ddoc"
    RAW = "raw"
