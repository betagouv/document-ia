import zxingcpp

from document_ia_infra.data.event.schema.barcode import DataMatrix, QrCode
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode import (
    BaseExtractBarcode,
)
from document_ia_worker.workflow.step.extract_barcode_data.base_extract_barcode_2ddoc import (
    BaseExtractBarcode2DDoc,
)
from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data import (
    _read_barcodes_compat,
)


def test_decode_datamatrix_variant():
    img = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode("TEST_DM_DATA", zxingcpp.BarcodeFormat.DataMatrix)
    )
    barcodes = zxingcpp.read_barcodes(img)
    assert len(barcodes) == 1

    base = BaseExtractBarcode()
    variant, key, is_spec = base._decode_barcode_to_variant(barcodes[0], 1)

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
    variant, key, is_spec = base._decode_barcode_to_variant(barcodes[0], 2)

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
    variant, key, is_spec = base_2ddoc._decode_barcode_to_variant(barcodes[0], 1)

    assert isinstance(variant, DataMatrix)
    assert variant.raw_data == "NON_2DDOC_DM"
    assert key == "dm:NON_2DDOC_DM"
    assert not is_spec


def test_read_barcodes_compat_with_target_formats():
    target_formats = zxingcpp.barcode_formats_from_str("DataMatrix|QRCode")
    img = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode("COMPAT_DM", zxingcpp.BarcodeFormat.DataMatrix)
    )
    barcodes = _read_barcodes_compat(img, formats=target_formats, is_from_crops=False)
    assert len(barcodes) == 1
    assert barcodes[0].text == "COMPAT_DM"
