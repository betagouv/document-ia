import pathlib
import pytest

from document_ia_worker.core.deepseek_ocr.deepseek_ocr_service import DeepseekOcrService
from document_ia_worker.core.deepseek_ocr.deepseek_ocr_settings import deepseek_ocr_settings


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_extract_text_from_image_e2e_success():
    """Test e2e réel qui appelle l'API Nanonets si les variables d'env sont configurées.
    Skippé automatiquement sinon.
    """
    if deepseek_ocr_settings.DEEPSEEK_OCR_API_KEY is None or deepseek_ocr_settings.DEEPSEEK_OCR_BASE_URL is None:
        pytest.skip("DEEPSEEK_OCR_API_KEY / DEEPSEEK_OCR_BASE_URL non configurés, skip e2e")

    fixture_path = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "test_download_file.pdf"
    service = DeepseekOcrService()

    result = await service.extract_text_from_image(str(fixture_path))

    # Assertions minimales pour e2e réel
    assert result is not None
    assert result.success is True
    assert isinstance(result.content, str) and len(result.content) > 0


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_extract_text_from_image_e2e_unauthorized():
    """Test e2e d'échec avec une clé invalide (401 attendu côté service).
    On force une mauvaise clé sur l'instance du service.
    """
    if deepseek_ocr_settings.DEEPSEEK_OCR_API_KEY is None or deepseek_ocr_settings.DEEPSEEK_OCR_BASE_URL is None:
        pytest.skip("DEEPSEEK_OCR_API_KEY / DEEPSEEK_OCR_BASE_URL non configurés, skip e2e")

    fixture_path = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "test_download_file.pdf"
    service = DeepseekOcrService()

    # Forcer une clé invalide et conserver la base_url valide
    service.api_key = "invalid-key-for-test"
    service.base_url = deepseek_ocr_settings.DEEPSEEK_OCR_BASE_URL

    result = await service.extract_text_from_image(str(fixture_path))

    # Avec une clé invalide, on s'attend à un échec (le service renvoie un JSON sans "text" ou 401)
    assert result is not None
    assert result.success is False
    assert result.content == ""