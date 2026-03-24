import logging
from typing import (
    Optional,
    Any,
    cast,
    Iterable,
    TypedDict,
)

import cv2
import numpy as np
import zxingcpp
from numpy.typing import NDArray
from qrdet import QRDetector

from document_ia_worker.core.barcode_settings import barcode_settings
from document_ia_worker.workflow.main_workflow_context import StepMetadata
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode_2ddoc import (
    BaseExtractBarcode2DDoc,
)
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode import (
    BarcodeLike,
)
from document_ia_worker.workflow.step.step_result.barcode_result import (
    BarcodeResult,
    PageResult,
)

logger = logging.getLogger(__name__)

ImageArray = NDArray[np.uint8]
FloatArray = NDArray[np.floating[Any]]
MatLike = NDArray[np.generic]


class QRDetDetection(TypedDict, total=False):
    bbox_xyxy: list[float] | FloatArray


ZXINGCPP: Any = zxingcpp
_qrdet_detector: Optional[QRDetector] = None


# This method is used to read barcodes using ZXingCPP, with some compatibility handling for different return types and optional upscaling for crops.
def _read_barcodes_compat(
    image: MatLike,
    formats: Any = None,
    is_from_crops: bool = False,
) -> list[BarcodeLike]:
    if is_from_crops:
        image_scaled = _upscale_crop(cast(ImageArray, image), scale=2)
        barcodes = cast(
            list[BarcodeLike],
            ZXINGCPP.read_barcodes(image_scaled, formats=formats),
        )
        has_datamatrix = any(
            str(barcode.format) == "BarcodeFormat.DataMatrix" for barcode in barcodes
        )
        if not has_datamatrix:
            logger.info(
                "Last chance we try upscaling 3x for better QR code detection in crops..."
            )
            image_scaled = _upscale_crop(cast(ImageArray, image), scale=3)
            return cast(
                list[BarcodeLike],
                ZXINGCPP.read_barcodes(image_scaled, formats=formats),
            )
        return barcodes

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


# This method will iterate over the detections from QRDet, crop the corresponding regions from the original image, add a white border around them, and return the list of cropped images.
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


# This workflow step is optimized for 2DDoc detection: it performs a fast global scan with ZXingCPP
# to read 2DDoc and QR codes on each page. If no 2DDoc (Ants2DDoc) is decoded in that pass,
# it runs a YOLO-based detector (QRDet) to isolate candidate 2DDoc regions, then adds a white
# background and upscales the crops to improve ZXingCPP decoding. The final output aggregates
# and de-duplicates all detected codes (2DDoc and QRCode) across the page.
class ExtractBarcode2DDocData(BaseExtractBarcode2DDoc):
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
            page_barcode_data, seen_keys, has_ants = self._decode_barcodes_batch(
                barcodes,
                idx + 1,
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
                    crop_variants, seen_keys, _ = self._decode_barcodes_batch(
                        crop_barcodes,
                        idx + 1,
                        seen_keys,
                    )
                    page_barcode_data.extend(crop_variants)

            if not page_barcode_data:
                continue
            barcodes_data.append(
                PageResult(page_number=idx + 1, barcodes=page_barcode_data)
            )
        return BarcodeResult(pages=barcodes_data), None
