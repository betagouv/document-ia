import logging
from typing import (
    Optional,
    Any,
    runtime_checkable,
    Protocol,
    Iterable,
)

from fr_2ddoc_parser.api import decode_2d_doc

from document_ia_infra.core.model.typed_generic_model import GenericProperty
from document_ia_infra.data.event.schema.barcode import (
    Ants2DDoc,
    QrCode,
    BarcodePosition,
    BarcodeVariant,
    DataMatrix,
)
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.barcode_result import (
    BarcodeResult,
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
        Returns (variant, key, is_ants_2ddoc).
        """
        format_str = str(barcode.format)

        if format_str == "BarcodeFormat.DataMatrix":
            key = f"dm:{barcode.text}"
            try:
                result = decode_2d_doc(barcode.text)
                return (
                    Ants2DDoc(
                        position=self._map_position_like_to_model(barcode.position),
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
                        position=self._map_position_like_to_model(barcode.position),
                        raw_data=barcode.text,
                        page_number=page_number,
                    ),
                    key,
                    False,
                )

        if format_str == "BarcodeFormat.QRCode":
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
        Returns (variants, updated_seen_keys, has_ants_2ddoc).
        """
        variants: list[BarcodeVariant] = []
        if seen_keys is None:
            seen_keys = set()
        has_ants = False

        for barcode in barcodes:
            variant, key, is_ants = self._decode_barcode_to_variant(
                barcode,
                page_number,
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
