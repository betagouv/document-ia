import logging
import threading
from typing import (
    Optional,
    Any,
    runtime_checkable,
    Protocol,
    Iterable,
    cast,
)

import cv2
import numpy as np
from numpy.typing import NDArray

from document_ia_infra.data.event.schema.barcode import (
    QrCode,
    BarcodePosition,
    BarcodeVariant,
    DataMatrix,
)
from document_ia_worker.core.barcode_settings import barcode_settings
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.barcode_result import (
    BarcodeResult,
)
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)

logger = logging.getLogger(__name__)

ImageArray = NDArray[np.uint8]
MatLike = NDArray[np.generic]

_BARCODE_LOCK = threading.Lock()

__all__ = [
    "PointLike",
    "PositionLike",
    "BarcodeLike",
    "BaseExtractBarcode",
    "ImageArray",
    "MatLike",
    "_BARCODE_LOCK",
    "_rescale_barcode_position",
    "load_and_downscale_barcode_image",
]


def _rescale_barcode_position(
    position: BarcodePosition,
    scale: float,
) -> BarcodePosition:
    """
    Rescale barcode corner coordinates from a downscaled image space (scale < 1.0)
    back to the original document's coordinate space.
    """
    if scale >= 1.0 or scale <= 0:
        return position

    def rescale_point(pt: tuple[int, int]) -> tuple[int, int]:
        return (int(round(pt[0] / scale)), int(round(pt[1] / scale)))

    return BarcodePosition(
        top_left=rescale_point(position.top_left),
        top_right=rescale_point(position.top_right),
        bottom_right=rescale_point(position.bottom_right),
        bottom_left=rescale_point(position.bottom_left),
    )


def load_and_downscale_barcode_image(
    file: str,
) -> tuple[ImageArray | None, float]:
    """
    Loads an image from file and downscales it using cv2.INTER_AREA if its maximum dimension
    exceeds barcode_settings.MAX_BARCODE_IMAGE_DIM.
    Returns (image, scale_factor).
    """
    img_raw = cv2.imread(file)
    if img_raw is None:
        logger.error(f"Impossible de lire l'image: {file}")
        return None, 1.0

    height, width = img_raw.shape[:2]
    max_dim = max(height, width)
    scale = 1.0

    if max_dim > barcode_settings.MAX_BARCODE_IMAGE_DIM:
        scale = barcode_settings.MAX_BARCODE_IMAGE_DIM / max_dim
        new_width = max(1, int(round(width * scale)))
        new_height = max(1, int(round(height * scale)))
        img = cast(
            ImageArray,
            cv2.resize(
                img_raw,
                (new_width, new_height),
                interpolation=cv2.INTER_AREA,
            ),
        )
        del img_raw
        return img, scale

    return cast(ImageArray, img_raw), scale


@runtime_checkable
class PointLike(Protocol):
    x: int
    y: int


@runtime_checkable
class PositionLike(Protocol):
    bottom_left: PointLike
    bottom_right: PointLike
    top_left: PointLike
    top_right: PointLike


@runtime_checkable
class BarcodeLike(Protocol):
    text: str
    format: Any
    content_type: str
    position: PositionLike


class BaseExtractBarcode(BaseStep[BarcodeResult]):
    preprocess_file_result: Optional[PreprocessFileResult] = None

    def get_context_result_key(self) -> str:
        return BarcodeResult.__name__

    def inject_workflow_context(self, context: dict[str, Any]):
        not_typed_data = context.get(PreprocessFileResult.__name__)
        if not_typed_data is None or not isinstance(
            not_typed_data, PreprocessFileResult
        ):
            raise ValueError("PreprocessFileReturnData not found in context")
        self.preprocess_file_result = not_typed_data

    async def _prepare_step(self):
        if self.preprocess_file_result is None:
            raise ValueError("PreprocessFileResult not injected in context")

    def _map_position_like_to_model(self, position: PositionLike) -> BarcodePosition:
        return BarcodePosition(
            bottom_left=(position.bottom_left.x, position.bottom_left.y),
            bottom_right=(position.bottom_right.x, position.bottom_right.y),
            top_left=(position.top_left.x, position.top_left.y),
            top_right=(position.top_right.x, position.top_right.y),
        )

    def _decode_barcode_to_variant(
        self,
        barcode: BarcodeLike,
        page_number: int,
    ) -> tuple[Optional[BarcodeVariant], Optional[str], bool]:
        """
        Decodes a single barcode into a BarcodeVariant.
        Returns (variant, key, is_specialized_variant).
        """
        format_name = getattr(barcode.format, "name", str(barcode.format))

        if format_name in ("DataMatrix", "BarcodeFormat.DataMatrix", "Data Matrix"):
            key = f"dm:{barcode.text}"
            return (
                DataMatrix(
                    position=self._map_position_like_to_model(barcode.position),
                    raw_data=barcode.text,
                    page_number=page_number,
                ),
                key,
                False,
            )

        if format_name in ("QRCode", "BarcodeFormat.QRCode", "QR Code"):
            key = f"qr:{barcode.text}"
            return (
                QrCode(
                    position=self._map_position_like_to_model(barcode.position),
                    raw_data=barcode.text,
                    page_number=page_number,
                ),
                key,
                False,
            )

        return None, None, False

    def _decode_barcodes_batch(
        self,
        barcodes: Iterable[BarcodeLike],
        page_number: int,
        seen_keys: Optional[set[str]] = None,
    ) -> tuple[list[BarcodeVariant], set[str], bool]:
        """
        Processes a batch of barcodes, handling deduplication.
        Returns (variants, updated_seen_keys, has_specialized_variant).
        """
        variants: list[BarcodeVariant] = []
        if seen_keys is None:
            seen_keys = set()
        has_specialized = False

        for barcode in barcodes:
            variant, key, is_specialized = self._decode_barcode_to_variant(
                barcode,
                page_number,
            )
            if variant is None or key is None:
                continue
            if key in seen_keys:
                continue
            seen_keys.add(key)
            variants.append(variant)
            if is_specialized:
                has_specialized = True

        return variants, seen_keys, has_specialized
