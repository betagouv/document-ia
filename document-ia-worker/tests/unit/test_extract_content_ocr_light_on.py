import base64
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import cv2
import httpx
import numpy as np
import pytest

from document_ia_worker.workflow.step.extract_content_ocr.extract_content_ocr_light_on import (
    ExtractContentOcrLightOnStep,
)
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)
from document_ia_worker.workflow.step.step_result.barcode_result import (
    BarcodeResult,
    PageResult,
)
from document_ia_infra.data.event.schema.barcode import (
    QrCode,
    BarcodePosition,
)

def _make_test_image(path: Path) -> Path:
    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path

@pytest.fixture
def mock_openai_settings(monkeypatch):
    from document_ia_infra.openai.openai_settings import openai_settings
    monkeypatch.setattr(openai_settings, "OPENAI_BASE_URL", "https://fake.url/v1")
    secret_mock = MagicMock()
    secret_mock.get_secret_value.return_value = "fake_key"
    monkeypatch.setattr(openai_settings, "OPENAI_API_KEY", secret_mock)

@pytest.mark.asyncio
async def test_extract_content_ocr_light_on_success(main_workflow_context, tmp_path, mock_openai_settings):
    img_path = _make_test_image(tmp_path / "page_1.png")

    step = ExtractContentOcrLightOnStep(main_workflow_context)
    step.inject_workflow_context({
        PreprocessFileResult.__name__: PreprocessFileResult(output_files_path=[str(img_path)])
    })

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello World"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result, meta = await step.execute()

        assert len(result.pages) == 1
        assert result.pages[0].page_number == 1
        assert result.pages[0].text == "Hello World"
        assert result.pages[0].has_failed is False
        mock_post.assert_called_once()

@pytest.mark.asyncio
async def test_extract_content_ocr_light_on_with_barcodes(main_workflow_context, tmp_path, mock_openai_settings, monkeypatch):
    img_path = _make_test_image(tmp_path / "page_1.png")

    step = ExtractContentOcrLightOnStep(main_workflow_context)

    barcode_result = BarcodeResult(
        pages=[
            PageResult(
                page_number=1,
                barcodes=[
                    QrCode(
                        position=BarcodePosition(
                            top_left=(10, 10),
                            top_right=(20, 10),
                            bottom_right=(20, 20),
                            bottom_left=(10, 20),
                        ),
                        page_number=1,
                        raw_data="qr_data"
                    )
                ]
            )
        ]
    )

    step.inject_workflow_context({
        PreprocessFileResult.__name__: PreprocessFileResult(output_files_path=[str(img_path)]),
        BarcodeResult.__name__: barcode_result
    })

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Masked text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    import document_ia_worker.workflow.step.extract_content_ocr.extract_content_ocr_light_on as light_on_module

    orig_fillPoly = light_on_module.cv2.fillPoly
    fill_poly_called = False
    def fake_fill_poly(img, pts, color):
        nonlocal fill_poly_called
        fill_poly_called = True
        return orig_fillPoly(img, pts, color)

    monkeypatch.setattr(light_on_module.cv2, "fillPoly", fake_fill_poly)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result, meta = await step.execute()

        assert len(result.pages) == 1
        assert result.pages[0].text == "Masked text"
        assert fill_poly_called is True

@pytest.mark.asyncio
async def test_extract_content_ocr_light_on_error_handling(main_workflow_context, tmp_path, mock_openai_settings):
    img_path = _make_test_image(tmp_path / "page_1.png")

    step = ExtractContentOcrLightOnStep(main_workflow_context)
    step.inject_workflow_context({
        PreprocessFileResult.__name__: PreprocessFileResult(output_files_path=[str(img_path)])
    })

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.HTTPError("Network error")
        result, meta = await step.execute()

        assert len(result.pages) == 1
        assert result.pages[0].has_failed is True
        assert result.pages[0].text is None
