from enum import Enum
from typing import Any, Annotated, Union, Literal

from pydantic import BaseModel, Field


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


class BarcodeModel(BaseModel):
    position: BarcodePosition
    page_number: int


class Ants2DDoc(BarcodeModel):
    type: Literal[BarcodeType.DATA_MATRIX] = BarcodeType.DATA_MATRIX
    position: BarcodePosition
    is_valid: bool
    data: Any


class QrCode(BarcodeModel):
    type: Literal[BarcodeType.QR] = BarcodeType.QR
    position: BarcodePosition
    data: str


BarcodeVariant = Annotated[Union[Ants2DDoc, QrCode], Field(discriminator="type")]
