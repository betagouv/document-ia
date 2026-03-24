import logging
from typing import Optional

from fr_2ddoc_parser.api import decode_2d_doc

from document_ia_infra.core.model.typed_generic_model import GenericProperty
from document_ia_infra.data.event.schema.barcode import (
    Ants2DDoc,
    BarcodeVariant,
    DataMatrix,
)
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode import (
    BaseExtractBarcode,
    BarcodeLike,
)

logger = logging.getLogger(__name__)


class BaseExtractBarcode2DDoc(BaseExtractBarcode):
    """
    Intermediate base class for steps that need to parse 2D-Doc content.
    """

    def _decode_barcode_to_variant(
        self,
        barcode: BarcodeLike,
        page_number: int,
    ) -> tuple[Optional[BarcodeVariant], Optional[str], bool]:
        """
        Specialized decoding for 2DDoc format.
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

        return super()._decode_barcode_to_variant(barcode, page_number)
