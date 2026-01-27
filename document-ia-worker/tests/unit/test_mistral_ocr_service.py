import pathlib
import pytest

from document_ia_worker.core.ocr.mistral.mistral_http_ocr_service import MistralHttpOcrService
from document_ia_worker.core.ocr.mistral.mistral_ocr_settings import mistral_ocr_settings


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_extract_text_from_image_e2e_success():
    """Test e2e réel qui appelle l'API Mistral OCR si les variables d'env sont configurées.
    Skippé automatiquement sinon.
    """
    if (
        mistral_ocr_settings.MISTRAL_OCR_API_KEY is None
        or mistral_ocr_settings.MISTRAL_ORC_BASE_URL is None
    ):
        pytest.skip("MISTRAL_OCR_API_KEY / MISTRAL_ORC_BASE_URL non configurés, skip e2e")

    fixture_path = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "test_download_file.pdf"
    service = MistralHttpOcrService()

    # Le service Mistral nécessite le mime_type pour construire l'URL data
    result = await service.extract_text_from_image(str(fixture_path), mime_type="application/pdf")

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
    if (
        mistral_ocr_settings.MISTRAL_OCR_API_KEY is None
        or mistral_ocr_settings.MISTRAL_ORC_BASE_URL is None
    ):
        pytest.skip("MISTRAL_OCR_API_KEY / MISTRAL_ORC_BASE_URL non configurés, skip e2e")

    fixture_path = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "test_download_file.pdf"
    service = MistralHttpOcrService()

    # Forcer une clé invalide et conserver la base_url valide
    service.get_api_key = "invalid-key-for-test"
    service.base_url = mistral_ocr_settings.MISTRAL_ORC_BASE_URL

    result = await service.extract_text_from_image(str(fixture_path), mime_type="application/pdf")

    # Avec une clé invalide, on s'attend à un échec (le service renvoie une erreur HTTP ou un JSON vide)
    assert result is not None
    assert result.success is False
    assert result.content == ""
