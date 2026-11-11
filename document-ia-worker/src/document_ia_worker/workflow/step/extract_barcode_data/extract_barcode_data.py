import logging
from typing import Optional, cast

import zxingcpp

from document_ia_infra.redis.progress_tracker import get_current_progress_tracker
from document_ia_worker.workflow.main_workflow_context import StepMetadata
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode_2ddoc import (
    BaseExtractBarcode2DDoc,
)
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode import (
    _BARCODE_LOCK,
    _rescale_barcode_position,
    load_and_downscale_barcode_image,
    BarcodeLike,
    ImageArray,
)
from document_ia_worker.workflow.step.step_result.barcode_result import (
    BarcodeResult,
    PageResult,
)

logger = logging.getLogger(__name__)


# Deprecated step, kept for backward compatibility. Use ExtractBarcode2DDocData or ExtractBarcodeRawData instead.
class ExtractBarcodeData(BaseExtractBarcode2DDoc):
    async def _execute_internal(self) -> tuple[BarcodeResult, Optional[StepMetadata]]:
        assert self.preprocess_file_result is not None

        barcodes_data: list[PageResult] = []

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
                try:
                    img, scale = load_and_downscale_barcode_image(file)
                    if img is None:
                        continue

                    barcodes: list[BarcodeLike] = cast(
                        list[BarcodeLike],
                        zxingcpp.read_barcodes(img),  # pyright: ignore [reportUnknownMemberType]
                    )

                    if not barcodes:
                        continue

                    page_barcode_data, _, _ = self._decode_barcodes_batch(
                        barcodes, idx + 1
                    )

                    if scale < 1.0:
                        for variant in page_barcode_data:
                            variant.position = _rescale_barcode_position(
                                variant.position, scale
                            )

                    if page_barcode_data:
                        barcodes_data.append(
                            PageResult(page_number=idx + 1, barcodes=page_barcode_data)
                        )
                finally:
                    del img

        return BarcodeResult(pages=barcodes_data), None
