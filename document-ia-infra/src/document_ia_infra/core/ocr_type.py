from enum import Enum


class OCRType(str, Enum):
    TESSERACT = "TESSERACT"
    NANONETS = "NANONETS"
    DEEPSEEK = "DEEPSEEK"
    MARKER = "MARKER"
    MISTRAL = "MISTRAL"
