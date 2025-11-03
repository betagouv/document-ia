from pydantic import BaseModel

from document_ia_infra.data.event.schema.barcode import BarcodeVariant


class PageResult(BaseModel):
    page_number: int
    barcodes: list[BarcodeVariant]


class BarcodeResult(BaseModel):
    pages: list[PageResult]
