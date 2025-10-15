from enum import Enum
from typing import Any, Union

from pydantic import BaseModel


class BarcodeType(str, Enum):
    QR = "QR"
    CODE_128 = "CODE_128"
    EAN_13 = "EAN_13"
    UPC_A = "UPC_A"
    PDF_417 = "PDF_417"
    DATA_MATRIX = "DATA_MATRIX"
    AZTEC = "AZTEC"


class BarcodePosition(BaseModel):
    top_left: tuple[int, int]
    top_right: tuple[int, int]
    bottom_right: tuple[int, int]
    bottom_left: tuple[int, int]


class Ants2DDoc(BaseModel):
    type: BarcodeType = BarcodeType.DATA_MATRIX
    position: BarcodePosition
    is_valid: bool
    data: Any


class QrCode(BaseModel):
    type: BarcodeType = BarcodeType.QR
    position: BarcodePosition
    data: str


type BarcodeData = Union[Ants2DDoc, QrCode]


class PageResult(BaseModel):
    page_number: int
    barcodes: list[BarcodeData]


class BarcodeResult(BaseModel):
    pages: list[PageResult]
