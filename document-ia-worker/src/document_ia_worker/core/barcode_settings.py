from typing import Literal

from pydantic import Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class BarcodeSettings(BaseDocumentIaSettings):
    QRDET_MODEL_SIZE: Literal["n", "s", "m", "l"] = Field(
        default="s",
        description="Size of the model for QRcode and barcode detection. Can be 'n', 's', 'm' or 'l'. Larger models are more accurate but slower.",
    )


barcode_settings = BarcodeSettings()
