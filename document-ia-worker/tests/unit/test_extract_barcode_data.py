from typing import Any, cast
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import zxingcpp
from cv2.typing import MatLike

from document_ia_infra.data.event.schema.barcode import (
    BarcodePosition,
    DataMatrix,
    QrCode,
)
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode import (
    BarcodeLike,
    BaseExtractBarcode,
)
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode_2ddoc import (
    BaseExtractBarcode2DDoc,
)
from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data import (
    ExtractBarcode2DDocData,
    _read_barcodes_compat,
    _rescale_barcode_position,
)
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)


def test_decode_datamatrix_variant():
    img = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode("TEST_DM_DATA", zxingcpp.BarcodeFormat.DataMatrix)
    )
    barcodes = zxingcpp.read_barcodes(img)
    assert len(barcodes) == 1

    base = BaseExtractBarcode()
    variant, key, is_spec = base._decode_barcode_to_variant(
        cast(BarcodeLike, barcodes[0]), 1
    )

    assert isinstance(variant, DataMatrix)
    assert variant.raw_data == "TEST_DM_DATA"
    assert variant.page_number == 1
    assert key == "dm:TEST_DM_DATA"
    assert not is_spec


def test_decode_qrcode_variant():
    img = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode("TEST_QR_DATA", zxingcpp.BarcodeFormat.QRCode)
    )
    barcodes = zxingcpp.read_barcodes(img)
    assert len(barcodes) == 1

    base = BaseExtractBarcode()
    variant, key, is_spec = base._decode_barcode_to_variant(
        cast(BarcodeLike, barcodes[0]), 2
    )

    assert isinstance(variant, QrCode)
    assert variant.raw_data == "TEST_QR_DATA"
    assert variant.page_number == 2
    assert key == "qr:TEST_QR_DATA"
    assert not is_spec


def test_2ddoc_datamatrix_fallback():
    img = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode("NON_2DDOC_DM", zxingcpp.BarcodeFormat.DataMatrix)
    )
    barcodes = zxingcpp.read_barcodes(img)
    assert len(barcodes) == 1

    base_2ddoc = BaseExtractBarcode2DDoc()
    variant, key, is_spec = base_2ddoc._decode_barcode_to_variant(
        cast(BarcodeLike, barcodes[0]), 1
    )

    assert isinstance(variant, DataMatrix)
    assert variant.raw_data == "NON_2DDOC_DM"
    assert key == "dm:NON_2DDOC_DM"
    assert not is_spec


def test_read_barcodes_compat_with_target_formats():
    target_formats = zxingcpp.barcode_formats_from_str("DataMatrix|QRCode")
    img = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode("COMPAT_DM", zxingcpp.BarcodeFormat.DataMatrix)
    )
    barcodes = _read_barcodes_compat(
        cast(MatLike, img), formats=target_formats, is_from_crops=False
    )
    assert len(barcodes) == 1
    assert barcodes[0].text == "COMPAT_DM"


def test_rescale_barcode_position() -> None:
    pos = BarcodePosition(
        top_left=(50, 100),
        top_right=(150, 100),
        bottom_right=(150, 200),
        bottom_left=(50, 200),
    )
    # Scale = 0.5 means image was halved, so coordinates must be doubled (x / 0.5 = 2*x)
    rescaled = _rescale_barcode_position(pos, scale=0.5)
    assert rescaled.top_left == (100, 200)
    assert rescaled.top_right == (300, 200)
    assert rescaled.bottom_right == (300, 400)
    assert rescaled.bottom_left == (100, 400)

    # Scale >= 1.0 does not change position
    unmodified = _rescale_barcode_position(pos, scale=1.0)
    assert unmodified == pos


def test_read_barcodes_compat_crop_exceeding_threshold_skips_upscale() -> None:
    # Crop dimension > 250 px (e.g. 300x300)
    large_crop = np.zeros((300, 300, 3), dtype=np.uint8)

    mock_barcode = MagicMock()
    mock_barcode.format.name = "DataMatrix"

    with (
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data._upscale_crop"
        ) as mock_upscale,
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data.ZXINGCPP.read_barcodes",
            return_value=[mock_barcode],
        ) as mock_read,
    ):
        result = _read_barcodes_compat(large_crop, is_from_crops=True)

        assert result == [mock_barcode]
        mock_upscale.assert_not_called()
        mock_read.assert_called_once_with(large_crop, formats=None)


def test_read_barcodes_compat_small_crop_upscales_2x() -> None:
    # Crop dimension <= 250 px (e.g. 100x100)
    small_crop = np.zeros((100, 100, 3), dtype=np.uint8)

    mock_barcode = MagicMock()
    mock_barcode.format.name = "DataMatrix"

    with (
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data._upscale_crop",
            return_value=small_crop,
        ) as mock_upscale,
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data.ZXINGCPP.read_barcodes",
            return_value=[mock_barcode],
        ),
    ):
        result = _read_barcodes_compat(small_crop, is_from_crops=True)

        assert result == [mock_barcode]
        # DataMatrix was found at scale 2x, so upscale 3x must not be called
        assert mock_upscale.call_count == 1
        scale_called = (
            mock_upscale.call_args[1].get("scale")
            if "scale" in mock_upscale.call_args[1]
            else mock_upscale.call_args[0][1]
        )
        assert scale_called == 2


def test_read_barcodes_compat_small_crop_fallback_upscales_3x_and_border() -> None:
    # Crop dimension <= 250 px with no DataMatrix found at 2x
    small_crop = np.zeros((100, 100, 3), dtype=np.uint8)

    with (
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data._upscale_crop",
            return_value=small_crop,
        ) as mock_upscale,
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data.ZXINGCPP.read_barcodes",
            return_value=[],
        ),
    ):
        result = _read_barcodes_compat(small_crop, is_from_crops=True)

        assert result == []
        # Fallback hierarchy: 2x clean, 3x clean, and 2x bordered
        assert mock_upscale.call_count == 3
        calls = [
            c[1].get("scale") if "scale" in c[1] else c[0][1]
            for c in mock_upscale.call_args_list
        ]
        assert calls == [2, 3, 2]


@pytest.mark.asyncio
async def test_extract_barcode_2ddoc_large_image_downscaled_and_positions_rescaled() -> (
    None
):
    step = ExtractBarcode2DDocData()
    step.preprocess_file_result = PreprocessFileResult(
        output_files_path=["/mock/page_1.png"],
    )

    # Large image: 4096 x 2048 (max_dim = 4096 > 2048) -> scale = 2048 / 4096 = 0.5
    raw_img = np.zeros((4096, 2048, 3), dtype=np.uint8)

    class DummyPoint:
        def __init__(self, x: int, y: int):
            self.x = x
            self.y = y

    class DummyPosition:
        def __init__(
            self,
            tl: tuple[int, int],
            tr: tuple[int, int],
            br: tuple[int, int],
            bl: tuple[int, int],
        ):
            self.top_left = DummyPoint(*tl)
            self.top_right = DummyPoint(*tr)
            self.bottom_right = DummyPoint(*br)
            self.bottom_left = DummyPoint(*bl)

    class DummyBarcode:
        def __init__(self, text: str, format_name: str, pos: DummyPosition):
            self.text = text
            self.format = format_name
            self.content_type = "text"
            self.position = pos

    detected_pos = DummyPosition((100, 200), (200, 200), (200, 300), (100, 300))
    detected_barcode = DummyBarcode("TEST_CODE", "QRCode", detected_pos)

    with (
        patch("cv2.imread", return_value=raw_img),
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data._read_barcodes_compat",
            return_value=[detected_barcode],
        ),
    ):
        result, _ = await step._execute_internal()

        assert len(result.pages) == 1
        page = result.pages[0]
        assert page.page_number == 1
        assert len(page.barcodes) == 1

        barcode_result = page.barcodes[0]
        # Position must be rescaled by 1 / 0.5 = 2.0
        assert barcode_result.position.top_left == (200, 400)
        assert barcode_result.position.top_right == (400, 400)
        assert barcode_result.position.bottom_right == (400, 600)
        assert barcode_result.position.bottom_left == (200, 600)
