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
        gt=0,
        description="Maximum dimension (width or height) in pixels for the whole page image during barcode scanning. Images exceeding this will be downscaled with INTER_AREA.",
    )
    MAX_CROP_DIM_FOR_UPSCALE: int = Field(
        default=300,
        gt=0,
        description="Maximum crop dimension (width or height) in pixels eligible for 2x/3x upscaling. Larger crops skip upscaling.",
    )
    MAX_BARCODE_IMAGE_PIXELS: int = Field(
        default=100_000_000,
        gt=0,
        description="Maximum total pixel count (width * height) permitted for an image before cv2.imread decompression, protecting against decompression bombs.",
    )


barcode_settings = BarcodeSettings()
