from typing import Literal

from pydantic import Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class BarcodeSettings(BaseDocumentIaSettings):
    QRDET_MODEL_SIZE: Literal["n", "s", "m", "l"] = Field(
        default="s",
        description="Size of the model for QRcode and barcode detection. Can be 'n', 's', 'm' or 'l'. Larger models are more accurate but slower.",
    )
    QRDET_WEIGHTS_DIR: str | None = Field(
        default=None,
        description="Directory path containing pre-downloaded weights for QRDet model.",
    )
    MAX_BARCODE_IMAGE_DIM: int = Field(
        default=2400,
        description="Maximum dimension (width or height) in pixels for the whole page image during barcode scanning. Images exceeding this will be downscaled with INTER_AREA.",
    )
    MAX_CROP_DIM_FOR_UPSCALE: int = Field(
        default=250,
        description="Maximum crop dimension (width or height) in pixels eligible for 2x/3x upscaling. Larger crops skip upscaling.",
    )


barcode_settings = BarcodeSettings()
