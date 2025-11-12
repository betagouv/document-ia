import pathlib
import pytest

from document_ia_worker.core.marker.marker_service import MarkerService
from document_ia_worker.core.marker.marker_settings import marker_settings


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_extract_text_from_image_e2e_success():
    """Test e2e réel qui appelle l'API Marker si les variables d'env sont configurées.
    Skippé automatiquement sinon.
    """
    if marker_settings.MARKER_API_KEY is None or marker_settings.MARKER_BASE_URL is None:
        pytest.skip("MARKER_API_KEY / MARKER_BASE_URL non configurés, skip e2e")

    fixture_path = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "test_download_file.pdf"
    service = MarkerService()

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
    if marker_settings.MARKER_API_KEY is None or marker_settings.MARKER_BASE_URL is None:
        pytest.skip("MARKER_API_KEY / MARKER_BASE_URL non configurés, skip e2e")

    fixture_path = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "test_download_file.pdf"
    service = MarkerService()

    # Forcer une clé invalide et conserver la base_url valide
    service.api_key = "invalid-key-for-test"
    service.base_url = marker_settings.MARKER_BASE_URL

    result = await service.extract_text_from_image(str(fixture_path))

    # Avec une clé invalide, on s'attend à un échec (le service renvoie un JSON sans "text" ou 401)
    assert result is not None
    assert result.success is False
    assert result.content == ""
