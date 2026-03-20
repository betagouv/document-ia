import logging
from typing import (
    Optional,
    Any,
    runtime_checkable,
    Protocol,
    cast,
    Iterable,
    TypedDict,
    Callable,
)

import cv2
import numpy as np
import zxingcpp
from fr_2ddoc_parser.api import decode_2d_doc
from numpy.typing import NDArray
from qrdet import QRDetector

from document_ia_infra.core.model.typed_generic_model import GenericProperty
from document_ia_infra.data.event.schema.barcode import (
    Ants2DDoc,
    QrCode,
    BarcodePosition,
    BarcodeVariant,
    DataMatrix,
)
from document_ia_worker.core.barcode_settings import barcode_settings
from document_ia_worker.workflow.main_workflow_context import StepMetadata
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.barcode_result import (
    BarcodeResult,
    PageResult,
)
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)

logger = logging.getLogger(__name__)


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


ImageArray = NDArray[np.uint8]
FloatArray = NDArray[np.floating[Any]]
MatLike = NDArray[np.generic]


class QRDetDetection(TypedDict, total=False):
    bbox_xyxy: list[float] | FloatArray


ZXINGCPP: Any = zxingcpp


def _read_barcodes_compat(
    image: MatLike,
    formats: Any = None,
    is_from_crops: bool = False,
) -> list[BarcodeLike]:
    if is_from_crops:
        image = _upscale_crop(cast(ImageArray, image), scale=3)

    return cast(
        list[BarcodeLike],
        ZXINGCPP.read_barcodes(image, formats=formats),
    )


_qrdet_detector: Optional[QRDetector] = None


def _get_qrdet_detector() -> QRDetector:
    global _qrdet_detector
    if _qrdet_detector is None:
        model_size = barcode_settings.QRDET_MODEL_SIZE
        _qrdet_detector = QRDetector(model_size=model_size)
    return _qrdet_detector


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


def _iter_qrdet_crops(
    img: ImageArray,
    detections: Iterable[QRDetDetection],
) -> list[ImageArray]:
    crops: list[ImageArray] = []
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
        x1, y1, x2, y2 = map(int, bbox_list)
        pad = int(min(x2 - x1, y2 - y1) * 0.02)
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(width, x2 + pad), min(height, y2 + pad)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = img[y1:y2, x1:x2]
        crop = _add_white_border(crop, border_ratio=0.25)
        crops.append(crop)
    return crops


def _barcode_key(barcode: BarcodeLike) -> Optional[str]:
    format_value = str(barcode.format)
    if format_value == "BarcodeFormat.DataMatrix":
        return f"dm:{barcode.text}"
    if format_value == "BarcodeFormat.QRCode":
        return f"qr:{barcode.text}"
    return None


def _decode_barcode(
    barcode: BarcodeLike,
    page_number: int,
    map_position: Callable[[PositionLike], BarcodePosition],
) -> tuple[Optional[BarcodeVariant], Optional[str], bool]:
    key = _barcode_key(barcode)
    if key is None:
        return None, None, False

    if key.startswith("dm:"):
        try:
            result = decode_2d_doc(barcode.text)
            return (
                Ants2DDoc(
                    position=map_position(barcode.position),
                    is_valid=result.is_valid,
                    raw_data=None if result.ants_type is not None else result.typed,
                    typed_data=[]
                    if result.ants_type is None
                    else GenericProperty.convert_pydantic_model(result.typed),
                    page_number=page_number,
                    ants_type=result.ants_type,
                    issue_date=result.header.issue_date,
                ),
                key,
                True,
            )
        except Exception as e:
            logger.warning(f"Failed to decode 2D Doc barcode : {e}")
            return (
                DataMatrix(
                    position=map_position(barcode.position),
                    raw_data=barcode.text,
                    page_number=page_number,
                ),
                key,
                False,
            )

    return (
        QrCode(
            position=map_position(barcode.position),
            raw_data=barcode.text,
            page_number=page_number,
        ),
        key,
        False,
    )


def _decode_barcodes(
    barcodes: Iterable[BarcodeLike],
    page_number: int,
    map_position: Callable[[PositionLike], BarcodePosition],
    seen_keys: Optional[set[str]] = None,
) -> tuple[list[BarcodeVariant], set[str], bool]:
    variants: list[BarcodeVariant] = []
    if seen_keys is None:
        seen_keys = set()
    has_ants = False

    for barcode in barcodes:
        variant, key, is_ants = _decode_barcode(
            barcode,
            page_number,
            map_position,
        )
        if variant is None or key is None:
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        variants.append(variant)
        if is_ants:
            has_ants = True

    return variants, seen_keys, has_ants


class ExtractBarcodeData(BaseStep[BarcodeResult]):
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
            raise ValueError("DownloadFileReturnData not injected in context")

    async def _execute_internal(self) -> tuple[BarcodeResult, Optional[StepMetadata]]:
        assert self.preprocess_file_result is not None

        barcodes_data: list[PageResult] = []
        target_formats: Any = (
            ZXINGCPP.BarcodeFormat.DataMatrix | ZXINGCPP.BarcodeFormat.QRCode
        )

        for idx, file in enumerate(self.preprocess_file_result.output_files_path):
            img_raw = cv2.imread(file)
            if img_raw is None:
                logger.error(f"Impossible de lire l'image: {file}")
                continue
            img = cast(ImageArray, img_raw)

            barcodes: list[BarcodeLike] = _read_barcodes_compat(
                img,
                target_formats,
                False,
            )
            page_barcode_data, seen_keys, has_ants = _decode_barcodes(
                barcodes,
                idx + 1,
                self._map_position_like_to_model,
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

                for crop in rois:
                    crop_barcodes = _read_barcodes_compat(
                        crop,
                        target_formats,
                        True,
                    )
                    if not crop_barcodes:
                        continue
                    crop_variants, seen_keys, _ = _decode_barcodes(
                        crop_barcodes,
                        idx + 1,
                        self._map_position_like_to_model,
                        seen_keys,
                    )
                    page_barcode_data.extend(crop_variants)

            if not page_barcode_data:
                continue
            barcodes_data.append(
                PageResult(page_number=idx + 1, barcodes=page_barcode_data)
            )
        return BarcodeResult(pages=barcodes_data), None

    def _map_position_like_to_model(self, position: PositionLike) -> BarcodePosition:
        return BarcodePosition(
            bottom_left=(position.bottom_left.x, position.bottom_left.y),
            bottom_right=(position.bottom_right.x, position.bottom_right.y),
            top_left=(position.top_left.x, position.top_left.y),
            top_right=(position.top_right.x, position.top_right.y),
        )
