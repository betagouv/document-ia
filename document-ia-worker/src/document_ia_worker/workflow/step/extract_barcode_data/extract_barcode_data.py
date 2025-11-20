import logging
from typing import Optional, Any, runtime_checkable, Protocol, cast

import cv2
import zxingcpp
from fr_2ddoc_parser.api import decode_2d_doc

from document_ia_infra.data.event.schema.barcode import (
    Ants2DDoc,
    QrCode,
    BarcodePosition,
    BarcodeVariant,
    DataMatrix,
)
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

        for idx, file in enumerate(self.preprocess_file_result.output_files_path):
            page_barcode_data: list[BarcodeVariant] = []
            img = cv2.imread(file)
            barcodes: list[BarcodeLike] = cast(
                list[BarcodeLike],
                zxingcpp.read_barcodes(img),  # pyright: ignore [reportUnknownMemberType]
            )
            if len(barcodes) == 0:
                continue
            for barcode in barcodes:
                if str(barcode.format) == "BarcodeFormat.DataMatrix":
                    try:
                        result = decode_2d_doc(barcode.text)
                        page_barcode_data.append(
                            Ants2DDoc(
                                position=self._map_position_like_to_model(
                                    barcode.position
                                ),
                                is_valid=result.is_valid,
                                data=result.typed,
                                page_number=idx + 1,
                            )
                        )
                    except Exception:
                        logger.warning("Failed to decode 2D Doc barcode")
                        page_barcode_data.append(
                            DataMatrix(
                                position=self._map_position_like_to_model(
                                    barcode.position
                                ),
                                data=barcode.text,
                                page_number=idx + 1,
                            )
                        )
                        continue
                elif str(barcode.format) == "BarcodeFormat.QRCode":
                    page_barcode_data.append(
                        QrCode(
                            position=self._map_position_like_to_model(barcode.position),
                            data=barcode.text,
                            page_number=idx + 1,
                        )
                    )
                else:
                    logger.warning(f"Unsupported barcode format: {barcode.format}")
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
