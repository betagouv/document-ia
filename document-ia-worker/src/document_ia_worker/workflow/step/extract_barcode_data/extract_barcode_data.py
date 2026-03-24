import logging
from typing import Optional, cast

import cv2
import zxingcpp

from document_ia_worker.workflow.main_workflow_context import StepMetadata
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode import (
    BaseExtractBarcode,
    BarcodeLike,
)
from document_ia_worker.workflow.step.step_result.barcode_result import (
    BarcodeResult,
    PageResult,
)

logger = logging.getLogger(__name__)


class ExtractBarcodeData(BaseExtractBarcode):
    async def _execute_internal(self) -> tuple[BarcodeResult, Optional[StepMetadata]]:
        assert self.preprocess_file_result is not None

        barcodes_data: list[PageResult] = []

        for idx, file in enumerate(self.preprocess_file_result.output_files_path):
            img = cv2.imread(file)
            barcodes: list[BarcodeLike] = cast(
                list[BarcodeLike],
                zxingcpp.read_barcodes(img),  # pyright: ignore [reportUnknownMemberType]
            )

            if not barcodes:
                continue

            page_barcode_data, _, _ = self._decode_barcodes_batch(barcodes, idx + 1)

            if page_barcode_data:
                barcodes_data.append(
                    PageResult(page_number=idx + 1, barcodes=page_barcode_data)
                )

        return BarcodeResult(pages=barcodes_data), None
