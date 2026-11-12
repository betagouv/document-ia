from typing import Any, cast
from unittest.mock import MagicMock, PropertyMock, patch
from PIL import Image

import cv2
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
    load_and_downscale_barcode_image,
)
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode_2ddoc import (
    BaseExtractBarcode2DDoc,
)
from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data import (
    ExtractBarcode2DDocData,
    _iter_qrdet_crops,
    _normalize_barcode_position,
    _offset_barcode_position,
    _read_barcodes_compat,
    _rescale_barcode_position,
)
from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_data import (
    ExtractBarcodeData,
)
from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_raw_data import (
    ExtractBarcodeRawData,
)
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)


class DummyPoint:
    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y


class DummyPosition:
    def __init__(
        self,
        tl: tuple[int, int],
        tr: tuple[int, int],
        br: tuple[int, int],
        bl: tuple[int, int],
    ) -> None:
        self.top_left = DummyPoint(*tl)
        self.top_right = DummyPoint(*tr)
        self.bottom_right = DummyPoint(*br)
        self.bottom_left = DummyPoint(*bl)


class DummyBarcode:
    def __init__(
        self,
        text: str,
        format_name: str,
        pos: DummyPosition,
        content_type: str = "text",
    ) -> None:
        self.text = text
        self.format = format_name
        self.content_type = content_type
        self.position = pos


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


def test_offset_barcode_position() -> None:
    pos = BarcodePosition(
        top_left=(10, 20),
        top_right=(60, 20),
        bottom_right=(60, 70),
        bottom_left=(10, 70),
    )
    offset_pos = _offset_barcode_position(pos, offset_x=500, offset_y=300)
    assert offset_pos.top_left == (510, 320)
    assert offset_pos.top_right == (560, 320)
    assert offset_pos.bottom_right == (560, 370)
    assert offset_pos.bottom_left == (510, 370)

    # Offset 0, 0 should return identical coordinates
    assert _offset_barcode_position(pos, offset_x=0, offset_y=0) == pos


def test_normalize_barcode_position() -> None:
    pos = DummyPosition((40, 60), (80, 60), (80, 100), (40, 100))
    barcode = DummyBarcode("TEST", "QRCode", pos)

    # 1. Upscale 2x, no pad -> divide by 2
    norm_2x = _normalize_barcode_position(cast(BarcodeLike, barcode), scale=2, pad=0)
    assert norm_2x.position.top_left.x == 20
    assert norm_2x.position.top_left.y == 30
    assert norm_2x.position.bottom_right.x == 40
    assert norm_2x.position.bottom_right.y == 50

    # 2. Scale 1, pad 15 -> subtract 15
    norm_pad = _normalize_barcode_position(cast(BarcodeLike, barcode), scale=1, pad=15)
    assert norm_pad.position.top_left.x == 25
    assert norm_pad.position.top_left.y == 45

    # 3. Scale 2, pad 15 -> divide by 2 then subtract 15
    norm_2x_pad = _normalize_barcode_position(
        cast(BarcodeLike, barcode), scale=2, pad=15
    )
    assert norm_2x_pad.position.top_left.x == 5  # 40/2 - 15 = 5
    assert norm_2x_pad.position.top_left.y == 15  # 60/2 - 15 = 15

    # 4. Scale 1, pad 0 -> unmodified barcode returned directly
    unmodified = _normalize_barcode_position(cast(BarcodeLike, barcode), scale=1, pad=0)
    assert unmodified is barcode


def test_read_barcodes_compat_crop_exceeding_threshold_skips_upscale() -> None:
    # Crop dimension > 300 px (e.g. 350x350)
    large_crop = np.zeros((350, 350, 3), dtype=np.uint8)
    mock_pos = DummyPosition((0, 0), (10, 0), (10, 10), (0, 10))
    mock_barcode = DummyBarcode("DM", "DataMatrix", mock_pos)

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


def test_read_barcodes_compat_small_crop_decoded_at_1x_skips_upscale() -> None:
    # QUAL-03: Isolated small crop (<= 250px) decoded directly at 1x resolution.
    # Must return immediately without any memory-consuming upscale allocation.
    small_crop = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_pos = DummyPosition((10, 10), (30, 10), (30, 30), (10, 30))
    mock_barcode = DummyBarcode("DM_1X", "DataMatrix", mock_pos)

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

        assert len(result) == 1
        assert result[0].text == "DM_1X"
        mock_upscale.assert_not_called()
        assert result[0].position.top_left.x == 10
        assert result[0].position.top_left.y == 10


def test_read_barcodes_compat_small_crop_upscales_2x() -> None:
    # Crop dimension <= 250 px (e.g. 100x100), fails at 1x, succeeds at 2x
    small_crop = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_pos = DummyPosition((20, 20), (40, 20), (40, 40), (20, 40))
    mock_barcode = DummyBarcode("DM", "DataMatrix", mock_pos)

    with (
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data._upscale_crop",
            return_value=small_crop,
        ) as mock_upscale,
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data.ZXINGCPP.read_barcodes",
            side_effect=[[], [mock_barcode]],
        ),
    ):
        result = _read_barcodes_compat(small_crop, is_from_crops=True)

        assert len(result) == 1
        # DataMatrix was found at scale 2x, so upscale 3x must not be called
        assert mock_upscale.call_count == 1
        scale_called = (
            mock_upscale.call_args[1].get("scale")
            if "scale" in mock_upscale.call_args[1]
            else mock_upscale.call_args[0][1]
        )
        assert scale_called == 2
        # Position must be normalized back to original crop coordinate space (divided by 2)
        assert result[0].position.top_left.x == 10
        assert result[0].position.top_left.y == 10


def test_read_barcodes_compat_small_crop_with_qrcode_skips_3x_and_border() -> None:
    # QUAL-02: Crop contains a QR Code decoded at 2x after 1x missed it.
    small_crop = np.zeros((120, 120, 3), dtype=np.uint8)
    mock_pos = DummyPosition((20, 40), (60, 40), (60, 80), (20, 80))
    mock_qr_barcode = DummyBarcode("QR_CODE_PAYLOAD", "QRCode", mock_pos)

    with (
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data._upscale_crop",
            return_value=small_crop,
        ) as mock_upscale,
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data.ZXINGCPP.read_barcodes",
            side_effect=[[], [mock_qr_barcode]],
        ),
    ):
        result = _read_barcodes_compat(small_crop, is_from_crops=True)

        assert len(result) == 1
        assert result[0].text == "QR_CODE_PAYLOAD"
        # Upscale must ONLY be called once with scale=2
        assert mock_upscale.call_count == 1
        scale_called = (
            mock_upscale.call_args[1].get("scale")
            if "scale" in mock_upscale.call_args[1]
            else mock_upscale.call_args[0][1]
        )
        assert scale_called == 2
        # Normalized coordinates (20/2, 40/2) -> (10, 20)
        assert result[0].position.top_left.x == 10
        assert result[0].position.top_left.y == 20


def test_read_barcodes_compat_small_crop_fallback_upscales_3x_and_border() -> None:
    # Crop dimension <= 250 px with no barcode found at 1x, 2x, 3x, 2x-border, 3x-border
    small_crop = np.zeros((100, 100, 3), dtype=np.uint8)

    with (
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data._upscale_crop",
            return_value=small_crop,
        ) as mock_upscale,
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data.ZXINGCPP.read_barcodes",
            return_value=[],
        ) as mock_read,
    ):
        result = _read_barcodes_compat(small_crop, is_from_crops=True)

        assert result == []
        # Fallback hierarchy: 2x clean, 3x clean, 2x bordered, 3x bordered
        assert mock_upscale.call_count == 4
        calls = [
            c[1].get("scale") if "scale" in c[1] else c[0][1]
            for c in mock_upscale.call_args_list
        ]
        assert calls == [2, 3, 2, 3]
        # ZXingCPP reads: 1x clean, 2x clean, 3x clean, 1x bordered, 2x bordered, 3x bordered -> exactly 6 passes, no fallthrough 7th pass
        assert mock_read.call_count == 6


@pytest.mark.asyncio
async def test_extract_barcode_2ddoc_large_image_downscaled_and_positions_rescaled() -> (
    None
):
    step = ExtractBarcode2DDocData()
    step.preprocess_file_result = PreprocessFileResult(
        output_files_path=["/mock/page_1.png"],
    )

    # Large image: 4800 x 2400 (max_dim = 4800 > 2400) -> scale = 2400 / 4800 = 0.5
    raw_img = np.zeros((4800, 2400, 3), dtype=np.uint8)

    detected_pos = DummyPosition((100, 200), (200, 200), (200, 300), (100, 300))
    detected_barcode = DummyBarcode("TEST_CODE", "QRCode", detected_pos)

    mock_pil = MagicMock()
    mock_pil.size = (2400, 4800)
    mock_pil.__enter__.return_value = mock_pil

    with (
        patch("PIL.Image.open", return_value=mock_pil),
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


@pytest.mark.asyncio
async def test_extract_barcode_2ddoc_a4_200dpi_not_downscaled() -> None:
    # QUAL-03: Standard A4 page rendered at 200 DPI has dimensions 1654 x 2338.
    # Since 2338 <= 2400, it must NOT be downscaled (scale = 1.0, cv2.resize not called).
    step = ExtractBarcode2DDocData()
    step.preprocess_file_result = PreprocessFileResult(
        output_files_path=["/mock/page_a4.png"],
    )
    a4_img = np.zeros((2338, 1654, 3), dtype=np.uint8)
    detected_pos = DummyPosition((100, 200), (200, 200), (200, 300), (100, 300))
    detected_barcode = DummyBarcode("A4_CODE", "QRCode", detected_pos)

    mock_detector = MagicMock()
    mock_detector.detect.return_value = []

    mock_pil = MagicMock()
    mock_pil.size = (1654, 2338)
    mock_pil.__enter__.return_value = mock_pil

    with (
        patch("PIL.Image.open", return_value=mock_pil),
        patch("cv2.imread", return_value=a4_img),
        patch("cv2.resize", wraps=cv2.resize) as spy_resize,
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data._get_qrdet_detector",
            return_value=mock_detector,
        ),
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data._read_barcodes_compat",
            return_value=[detected_barcode],
        ),
    ):
        result, _ = await step._execute_internal()

        assert len(result.pages) == 1
        # cv2.resize must not have been called for full-page downscaling
        spy_resize.assert_not_called()
        barcode_result = result.pages[0].barcodes[0]
        # Coordinates must remain exactly intact without downscaling
        assert barcode_result.position.top_left == (100, 200)
        assert barcode_result.position.bottom_right == (200, 300)


@pytest.mark.asyncio
async def test_extract_barcode_2ddoc_qrdet_crop_coordinates_projected_to_global_space() -> (
    None
):
    # QUAL-01: Full end-to-end geometry test for QRDet crop decoding:
    # 1. Image has size 4800 x 2400 -> scale = 2400 / 4800 = 0.5 (img resized to 2400 x 1200)
    # 2. First pass ZXing on full image returns nothing (has_ants = False)
    # 3. QRDet detects bbox [500, 300, 700, 500] in downscaled space (1200 x 2400)
    #    With pad = int(min(200, 200) * 0.02) = 4:
    #    Crop extracted at offset_x = 496, offset_y = 296, size 208 x 208 (<= 250 px)
    # 4. Small crop is upscaled 2x in _read_barcodes_compat
    # 5. ZXing in 2x upscaled crop finds barcode with top_left = (40, 60), bottom_right = (80, 100)
    # Expected coordinate math:
    # - Local crop space: (40 / 2, 60 / 2) = (20, 30)
    # - Downscaled page space: (20 + 496, 30 + 296) = (516, 326)
    # - Original page space: (516 / 0.5, 326 / 0.5) = (1032, 652)
    step = ExtractBarcode2DDocData()
    step.preprocess_file_result = PreprocessFileResult(
        output_files_path=["/mock/page_with_crop.png"],
    )
    raw_img = np.zeros((4800, 2400, 3), dtype=np.uint8)

    mock_detector = MagicMock()
    mock_detector.detect.return_value = [
        {"bbox_xyxy": np.array([500.0, 300.0, 700.0, 500.0])}
    ]

    detected_pos_in_2x_crop = DummyPosition((40, 60), (80, 60), (80, 100), (40, 100))
    crop_barcode = DummyBarcode("QR_CROP", "QRCode", detected_pos_in_2x_crop)

    # First ZXing call (full page) returns []
    # Second ZXing call (crop at 1x) returns []
    # Third ZXing call (crop scaled 2x) returns [crop_barcode]
    zxing_call_count = 0

    def mock_zxing_read(image: Any, formats: Any = None) -> list[Any]:
        nonlocal zxing_call_count
        zxing_call_count += 1
        if zxing_call_count <= 2:
            return []
        return [crop_barcode]

    mock_pil = MagicMock()
    mock_pil.size = (2400, 4800)
    mock_pil.__enter__.return_value = mock_pil

    with (
        patch("PIL.Image.open", return_value=mock_pil),
        patch("cv2.imread", return_value=raw_img),
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data._get_qrdet_detector",
            return_value=mock_detector,
        ),
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data.ZXINGCPP.read_barcodes",
            side_effect=mock_zxing_read,
        ),
    ):
        result, _ = await step._execute_internal()

        assert len(result.pages) == 1
        page = result.pages[0]
        assert len(page.barcodes) == 1
        barcode = page.barcodes[0]

        assert barcode.raw_data == "QR_CROP"
        # Verify coordinates: must NOT be (0, 0), nor (40, 60), nor (20, 30), nor (516, 326)
        # It must be projected all the way to the original 4800x2400 coordinate space!
        assert barcode.position.top_left == (1032, 652)
        # bottom_right: (80/2 + 496)/0.5 = (40 + 496)*2 = 536 * 2 = 1072, (100/2 + 296)/0.5 = (50 + 296)*2 = 346 * 2 = 692
        assert barcode.position.bottom_right == (1072, 692)


def test_iter_qrdet_crops_returns_independent_copies_and_ignores_nan_boxes() -> None:
    # QUAL-01 & QUAL-04:
    # 1. Crops must be detached copies (.base is None) to allow parent full-page image deallocation
    # 2. Bounding boxes containing NaN or inf must be skipped safely without ValueError
    full_img = np.zeros((1000, 1000, 3), dtype=np.uint8)
    detections: list[Any] = [
        {"bbox_xyxy": [100.0, 100.0, 300.0, 300.0]},
        {"bbox_xyxy": [float("nan"), 10.0, 200.0, 200.0]},
        {"bbox_xyxy": [50.0, float("inf"), 200.0, 200.0]},
        {"bbox_xyxy": np.array([400.0, 400.0, 600.0, 600.0])},
    ]

    crops = _iter_qrdet_crops(full_img, detections)

    assert len(crops) == 2
    for crop_tuple in crops:
        crop_matrix = crop_tuple.crop
        # In NumPy, a slice .copy() has base is None, while a view has base is not None
        assert crop_matrix.base is None


def test_normalize_barcode_position_clamps_negative_coordinates() -> None:
    # QUAL-04: If barcode corner lies inside padding (pt.x / scale < pad),
    # coordinate must be clamped to 0 to prevent negative positions.
    mock_pos = DummyPosition((2, 3), (20, 3), (20, 20), (2, 20))
    mock_barcode = DummyBarcode("CODE", "QRCode", mock_pos)

    # pad = 10, scale = 1 -> pt.x - pad = 2 - 10 = -8 -> clamped to 0
    normalized = _normalize_barcode_position(mock_barcode, scale=1, pad=10)

    assert normalized.position.top_left.x == 0
    assert normalized.position.top_left.y == 0


@pytest.mark.asyncio
async def test_extract_barcode_raw_data_downscales_and_handles_unreadable_image() -> (
    None
):
    # SEC-01: ExtractBarcodeRawData must downscale images exceeding MAX_BARCODE_IMAGE_DIM,
    # rescale detected positions, ignore unreadable images cleanly, and release memory in finally.
    step = ExtractBarcodeRawData()
    step.preprocess_file_result = PreprocessFileResult(
        output_files_path=["/mock/unreadable.png", "/mock/large_raw.png"],
    )

    large_img = np.zeros((4800, 2400, 3), dtype=np.uint8)
    detected_pos = DummyPosition((100, 200), (300, 200), (300, 400), (100, 400))
    detected_barcode = DummyBarcode("RAW_PAYLOAD", "QRCode", detected_pos)

    def mock_imread(path: str) -> Any:
        if "unreadable" in path:
            return None
        return large_img

    def mock_pil_open(path: str, *args: Any, **kwargs: Any) -> Any:
        mock_pil = MagicMock()
        mock_pil.size = (100, 100) if "unreadable" in path else (2400, 4800)
        mock_pil.__enter__.return_value = mock_pil
        return mock_pil

    with (
        patch("PIL.Image.open", side_effect=mock_pil_open),
        patch("cv2.imread", side_effect=mock_imread),
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_raw_data.zxingcpp.read_barcodes",
            return_value=[detected_barcode],
        ),
    ):
        result, _ = await step._execute_internal()

        # Unreadable page 1 was skipped cleanly, page 2 succeeded
        assert len(result.pages) == 1
        page = result.pages[0]
        assert page.page_number == 2
        assert len(page.barcodes) == 1
        b = page.barcodes[0]
        assert b.raw_data == "RAW_PAYLOAD"
        # Coordinates rescaled from 2400 max dim (scale = 2400 / 4800 = 0.5):
        # 100 / 0.5 = 200, 200 / 0.5 = 400
        assert b.position.top_left == (200, 400)
        assert b.position.bottom_right == (600, 800)


@pytest.mark.asyncio
async def test_extract_barcode_2ddoc_stops_when_watchdog_aborted() -> None:
    # QUAL-05: When watchdog fences the job (tracker.is_aborted == True),
    # barcode processing must break early without processing subsequent pages.
    step = ExtractBarcode2DDocData()
    step.preprocess_file_result = PreprocessFileResult(
        output_files_path=["/mock/page1.png", "/mock/page2.png", "/mock/page3.png"],
    )

    mock_tracker = MagicMock()
    # Not aborted on page 1, aborted on page 2
    mock_tracker.is_aborted = False

    page_img = np.zeros((1000, 1000, 3), dtype=np.uint8)
    detected_pos = DummyPosition((10, 10), (50, 10), (50, 50), (10, 50))
    detected_barcode = DummyBarcode("P1_CODE", "QRCode", detected_pos)

    call_count = 0

    def mock_load(path: str) -> tuple[Any, float]:
        nonlocal call_count
        call_count += 1
        # Set aborted as soon as page 1 is loaded
        mock_tracker.is_aborted = True
        return page_img, 1.0

    with (
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data.get_current_progress_tracker",
            return_value=mock_tracker,
        ),
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data.load_and_downscale_barcode_image",
            side_effect=mock_load,
        ),
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data._read_barcodes_compat",
            return_value=[detected_barcode],
        ),
    ):
        result, _ = await step._execute_internal()

        # Page 1 processed, then stopped before page 2 was loaded
        assert call_count == 1
        assert len(result.pages) == 1
        assert result.pages[0].page_number == 1


@pytest.mark.asyncio
async def test_extract_barcode_data_legacy_step_applies_downscale_and_lock() -> None:
    # SEC-01: Legacy ExtractBarcodeData step also applies lock and downscaling
    step = ExtractBarcodeData()
    step.preprocess_file_result = PreprocessFileResult(
        output_files_path=["/mock/legacy_page.png"],
    )

    detected_pos = DummyPosition((100, 200), (300, 200), (300, 400), (100, 400))
    detected_barcode = DummyBarcode("LEGACY_PAYLOAD", "QRCode", detected_pos)

    with (
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_data.load_and_downscale_barcode_image",
            return_value=(np.zeros((1200, 600, 3), dtype=np.uint8), 0.5),
        ),
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_data.zxingcpp.read_barcodes",
            return_value=[detected_barcode],
        ),
    ):
        result, _ = await step._execute_internal()

        assert len(result.pages) == 1
        assert result.pages[0].barcodes[0].raw_data == "LEGACY_PAYLOAD"
        # 100 / 0.5 = 200, 200 / 0.5 = 400
        assert result.pages[0].barcodes[0].position.top_left == (200, 400)


def test_load_and_downscale_barcode_image_rejects_decompression_bomb() -> None:
    # SEC-01: Images exceeding MAX_BARCODE_IMAGE_PIXELS or raising DecompressionBombError
    # must be rejected with (None, 1.0) without calling cv2.imread.
    mock_pil = MagicMock()
    mock_pil.size = (20000, 10000)  # 200 MP > 100 MP limit
    mock_pil.__enter__.return_value = mock_pil

    with (
        patch("PIL.Image.open", return_value=mock_pil),
        patch("cv2.imread") as mock_imread,
    ):
        img, scale = load_and_downscale_barcode_image("/fake/bomb.png")
        assert img is None
        assert scale == 1.0
        mock_imread.assert_not_called()

    with (
        patch(
            "PIL.Image.open",
            side_effect=Image.DecompressionBombError("Bomb detected"),
        ),
        patch("cv2.imread") as mock_imread,
    ):
        img, scale = load_and_downscale_barcode_image("/fake/bomb_err.png")
        assert img is None
        assert scale == 1.0
        mock_imread.assert_not_called()

    # Zero or negative dimensions
    mock_zero = MagicMock()
    mock_zero.size = (0, 100)
    mock_zero.__enter__.return_value = mock_zero
    with (
        patch("PIL.Image.open", return_value=mock_zero),
        patch("cv2.imread") as mock_imread,
    ):
        img, scale = load_and_downscale_barcode_image("/fake/zero.png")
        assert img is None
        assert scale == 1.0
        mock_imread.assert_not_called()


@pytest.mark.asyncio
async def test_extract_barcode_2ddoc_aborted_while_waiting_for_lock_skips_page() -> (
    None
):
    # QUAL-04: If job is aborted by watchdog while waiting for _BARCODE_LOCK,
    # the second abortion check inside with _BARCODE_LOCK must break immediately
    # without calling load_and_downscale_barcode_image or allocating memory.
    step = ExtractBarcode2DDocData()
    step.preprocess_file_result = PreprocessFileResult(
        output_files_path=["/mock/page1.png"],
    )

    mock_tracker = MagicMock()
    # First check (before lock) returns False; second check (inside lock) returns True
    type(mock_tracker).is_aborted = PropertyMock(side_effect=[False, True])

    with (
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data.get_current_progress_tracker",
            return_value=mock_tracker,
        ),
        patch(
            "document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data.load_and_downscale_barcode_image",
        ) as mock_load,
    ):
        result, _ = await step._execute_internal()

        assert len(result.pages) == 0
        mock_load.assert_not_called()
