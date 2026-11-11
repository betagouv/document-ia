from dataclasses import dataclass
import logging
import math
from typing import (
    Any,
    Iterable,
    NamedTuple,
    Optional,
    TypedDict,
    cast,
)

import cv2
import numpy as np
import zxingcpp
from numpy.typing import NDArray
from qrdet import QRDetector

from document_ia_infra.data.event.schema.barcode import BarcodePosition
from document_ia_infra.redis.progress_tracker import get_current_progress_tracker
from document_ia_worker.core.barcode_settings import barcode_settings
from document_ia_worker.workflow.main_workflow_context import StepMetadata
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode import (
    _BARCODE_LOCK,
    _rescale_barcode_position,
    load_and_downscale_barcode_image,
    BarcodeLike,
    ImageArray,
    MatLike,
    PointLike,
    PositionLike,
)
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode_2ddoc import (
    BaseExtractBarcode2DDoc,
)
from document_ia_worker.workflow.step.step_result.barcode_result import (
    BarcodeResult,
    PageResult,
)

logger = logging.getLogger(__name__)

FloatArray = NDArray[np.floating[Any]]


class QRDetDetection(TypedDict, total=False):
    bbox_xyxy: list[float] | FloatArray


ZXINGCPP: Any = zxingcpp
_qrdet_detector: Optional[QRDetector] = None
_QRDET_LOCK = _BARCODE_LOCK  # Backwards compatibility alias


@dataclass
class CropPoint:
    x: int
    y: int


@dataclass
class CropPosition:
    top_left: PointLike
    top_right: PointLike
    bottom_right: PointLike
    bottom_left: PointLike


class CropBarcode:
    """Wrapper adapting normalized crop coordinates back to BarcodeLike protocol."""

    def __init__(self, barcode: BarcodeLike, position: PositionLike) -> None:
        self.text: str = barcode.text
        self.format: Any = barcode.format
        self.content_type: str = getattr(barcode, "content_type", "text")
        self.position: PositionLike = position


def _offset_barcode_position(
    position: BarcodePosition,
    offset_x: int,
    offset_y: int,
) -> BarcodePosition:
    """
    Offset barcode corner coordinates by (offset_x, offset_y) to project
    from crop space back into the full page image coordinate space.
    """
    if offset_x == 0 and offset_y == 0:
        return position

    def offset_point(pt: tuple[int, int]) -> tuple[int, int]:
        return (pt[0] + offset_x, pt[1] + offset_y)

    return BarcodePosition(
        top_left=offset_point(position.top_left),
        top_right=offset_point(position.top_right),
        bottom_right=offset_point(position.bottom_right),
        bottom_left=offset_point(position.bottom_left),
    )


def _normalize_barcode_position(
    barcode: BarcodeLike,
    scale: int = 1,
    pad: int = 0,
) -> BarcodeLike:
    """
    Normalize barcode coordinates from an upscaled or padded crop back to the crop's original coordinate space.
    """
    if scale == 1 and pad == 0:
        return barcode

    def transform_point(pt: PointLike) -> CropPoint:
        x = max(0, int(round(pt.x / scale)) - pad)
        y = max(0, int(round(pt.y / scale)) - pad)
        return CropPoint(x=x, y=y)

    pos = CropPosition(
        top_left=transform_point(barcode.position.top_left),
        top_right=transform_point(barcode.position.top_right),
        bottom_right=transform_point(barcode.position.bottom_right),
        bottom_left=transform_point(barcode.position.bottom_left),
    )
    return CropBarcode(barcode=barcode, position=pos)


# This method is used to read barcodes using ZXingCPP, with some compatibility handling for different return types and optional upscaling for crops.
def _read_barcodes_compat(
    image: MatLike,
    formats: Any = None,
    is_from_crops: bool = False,
) -> list[BarcodeLike]:
    if is_from_crops:
        crop_h, crop_w = image.shape[:2]
        crop_dim = max(crop_h, crop_w)
        pad = int(min(crop_h, crop_w) * 0.15)

        # 1. Always try native 1x resolution on the isolated crop first (0 allocation, no cubic ringing)
        barcodes = cast(
            list[BarcodeLike],
            ZXINGCPP.read_barcodes(image, formats=formats),
        )
        if barcodes:
            return barcodes

        if crop_dim > barcode_settings.MAX_CROP_DIM_FOR_UPSCALE:
            # Fallback with border if no barcode detected on large crop
            bordered = _add_white_border(cast(ImageArray, image), border_ratio=0.15)
            try:
                raw_barcodes = cast(
                    list[BarcodeLike],
                    ZXINGCPP.read_barcodes(bordered, formats=formats),
                )
                return [
                    _normalize_barcode_position(b, scale=1, pad=pad)
                    for b in raw_barcodes
                ]
            finally:
                del bordered

        # 2. Small crop (<= MAX_CROP_DIM_FOR_UPSCALE): try 2x upscale, then immediately free it
        image_scaled_2x: ImageArray | None = _upscale_crop(
            cast(ImageArray, image), scale=2
        )
        try:
            barcodes_2x = cast(
                list[BarcodeLike],
                ZXINGCPP.read_barcodes(image_scaled_2x, formats=formats),
            )
            if barcodes_2x:
                return [
                    _normalize_barcode_position(b, scale=2, pad=0) for b in barcodes_2x
                ]
        finally:
            del image_scaled_2x

        # 3. Try 3x upscale on raw crop, then immediately free it
        logger.debug(
            "Last chance we try upscaling 3x for better QR code detection in crops..."
        )
        image_scaled_3x: ImageArray | None = _upscale_crop(
            cast(ImageArray, image), scale=3
        )
        try:
            barcodes_3x = cast(
                list[BarcodeLike],
                ZXINGCPP.read_barcodes(image_scaled_3x, formats=formats),
            )
            if barcodes_3x:
                return [
                    _normalize_barcode_position(b, scale=3, pad=0) for b in barcodes_3x
                ]
        finally:
            del image_scaled_3x

        # 4. Final fallback: add white border + upscale 2x (and 3x if still not decoded)
        bordered = _add_white_border(cast(ImageArray, image), border_ratio=0.15)
        try:
            bordered_scaled_2x: ImageArray | None = _upscale_crop(bordered, scale=2)
            try:
                raw_barcodes_2x = cast(
                    list[BarcodeLike],
                    ZXINGCPP.read_barcodes(bordered_scaled_2x, formats=formats),
                )
                if raw_barcodes_2x:
                    return [
                        _normalize_barcode_position(b, scale=2, pad=pad)
                        for b in raw_barcodes_2x
                    ]
            finally:
                del bordered_scaled_2x

            bordered_scaled_3x: ImageArray | None = _upscale_crop(bordered, scale=3)
            try:
                raw_barcodes_3x = cast(
                    list[BarcodeLike],
                    ZXINGCPP.read_barcodes(bordered_scaled_3x, formats=formats),
                )
                if raw_barcodes_3x:
                    return [
                        _normalize_barcode_position(b, scale=3, pad=pad)
                        for b in raw_barcodes_3x
                    ]
            finally:
                del bordered_scaled_3x
        finally:
            del bordered

    return cast(
        list[BarcodeLike],
        ZXINGCPP.read_barcodes(image, formats=formats),
    )


# This method initialize and load the model for QR code detection using QRDet, YOLO model.
# If the weights of the models are not already downloaded, it will download them from the official repository.
# And store it inside default lib cache directory`.
def _get_qrdet_detector() -> QRDetector:
    global _qrdet_detector
    if _qrdet_detector is None:
        model_size = barcode_settings.QRDET_MODEL_SIZE
        weights_folder = barcode_settings.QRDET_WEIGHTS_DIR
        if weights_folder:
            _qrdet_detector = QRDetector(
                model_size=model_size, weights_folder=weights_folder
            )
        else:
            _qrdet_detector = QRDetector(model_size=model_size)
    return _qrdet_detector


# This method will add a white border around the cropped image, to improve the detection of QR codes that are too close to the edge of the crop.
def _add_white_border(img: ImageArray, border_ratio: float = 0.15) -> ImageArray:
    if border_ratio <= 0:
        return img
    height, width = img.shape[:2]
    pad = int(min(height, width) * border_ratio)
    if pad <= 0:
        return img
    bordered = cv2.copyMakeBorder(
        img,
        pad,
        pad,
        pad,
        pad,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    return cast(ImageArray, bordered)


# This method will upscale the cropped image by a given scale factor, using cubic interpolation.
def _upscale_crop(img: ImageArray, scale: int = 2) -> ImageArray:
    if scale <= 1:
        return img
    height, width = img.shape[:2]
    resized = cv2.resize(
        img,
        (width * scale, height * scale),
        interpolation=cv2.INTER_CUBIC,
    )
    return cast(ImageArray, resized)


class QRDetCrop(NamedTuple):
    crop: ImageArray
    offset_x: int
    offset_y: int


# This method will iterate over the detections from QRDet, crop the corresponding regions from the original image,
# and return the list of independent cropped images.
def _iter_qrdet_crops(
    img: ImageArray,
    detections: Iterable[QRDetDetection],
) -> list[QRDetCrop]:
    crops: list[QRDetCrop] = []
    height, width = img.shape[:2]
    for det in detections:
        bbox = det.get("bbox_xyxy")
        if bbox is None:
            continue
        if isinstance(bbox, np.ndarray):
            if bbox.size != 4:
                continue
            bbox_list = cast(list[float], bbox.tolist())
        else:
            if len(bbox) != 4:
                continue
            bbox_list = bbox
        if not all(math.isfinite(v) for v in bbox_list):
            continue
        x1, y1 = math.floor(bbox_list[0]), math.floor(bbox_list[1])
        x2, y2 = math.ceil(bbox_list[2]), math.ceil(bbox_list[3])
        pad = int(min(x2 - x1, y2 - y1) * 0.02)
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(width, x2 + pad), min(height, y2 + pad)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = img[y1:y2, x1:x2].copy()
        crops.append(QRDetCrop(crop=crop, offset_x=x1, offset_y=y1))
    return crops


# This workflow step is optimized for 2DDoc detection: it performs a fast global scan with ZXingCPP
# to read 2DDoc and QR codes on each page. If no 2DDoc (Ants2DDoc) is decoded in that pass,
# it runs a YOLO-based detector (QRDet) to isolate candidate 2DDoc regions, then upscales
# the crops adaptively to improve ZXingCPP decoding. The final output aggregates
# and de-duplicates all detected codes (2DDoc and QRCode) across the page.
class ExtractBarcode2DDocData(BaseExtractBarcode2DDoc):
    async def _execute_internal(self) -> tuple[BarcodeResult, Optional[StepMetadata]]:
        assert self.preprocess_file_result is not None

        barcodes_data: list[PageResult] = []
        target_formats: Any = ZXINGCPP.barcode_formats_from_str("DataMatrix|QRCode")

        for idx, file in enumerate(self.preprocess_file_result.output_files_path):
            tracker = get_current_progress_tracker()
            if tracker is not None and tracker.is_aborted:
                logger.warning(
                    "Barcode extraction aborted by watchdog; stopping at page %d",
                    idx + 1,
                )
                break

            with _BARCODE_LOCK:
                img: ImageArray | None = None
                detections: list[QRDetDetection] = []
                rois: list[QRDetCrop] = []
                crop: ImageArray | None = None
                try:
                    img, scale = load_and_downscale_barcode_image(file)
                    if img is None:
                        continue

                    barcodes: list[BarcodeLike] = _read_barcodes_compat(
                        img,
                        target_formats,
                        False,
                    )
                    page_barcode_data, seen_keys, has_ants = (
                        self._decode_barcodes_batch(
                            barcodes,
                            idx + 1,
                        )
                    )

                    if scale < 1.0:
                        for variant in page_barcode_data:
                            variant.position = _rescale_barcode_position(
                                variant.position, scale
                            )

                    if not has_ants:
                        try:
                            logger.info(
                                "No suitable barcode found, trying QRDet for better QR code detection..."
                            )
                            detector = cast(Any, _get_qrdet_detector())
                            detections = cast(
                                list[QRDetDetection],
                                detector.detect(image=img, is_bgr=True),
                            )
                        except Exception as exc:
                            logger.warning(f"QRDet detection failed: {exc}")
                            detections = []

                        rois = _iter_qrdet_crops(img, detections)
                        # Free full-page image and QRDet masks BEFORE upscaling 2x/3x crops
                        img = None
                        detections = []

                        for crop_obj in rois:
                            crop, offset_x, offset_y = crop_obj
                            crop_barcodes = _read_barcodes_compat(
                                crop,
                                target_formats,
                                True,
                            )
                            if not crop_barcodes:
                                continue
                            crop_variants, seen_keys, _ = self._decode_barcodes_batch(
                                crop_barcodes,
                                idx + 1,
                                seen_keys,
                            )
                            for variant in crop_variants:
                                variant.position = _offset_barcode_position(
                                    variant.position, offset_x, offset_y
                                )
                                if scale < 1.0:
                                    variant.position = _rescale_barcode_position(
                                        variant.position, scale
                                    )
                            page_barcode_data.extend(crop_variants)
                            crop = None

                    if not page_barcode_data:
                        continue
                    barcodes_data.append(
                        PageResult(page_number=idx + 1, barcodes=page_barcode_data)
                    )
                finally:
                    del crop
                    del rois
                    del detections
                    del img

        return BarcodeResult(pages=barcodes_data), None
