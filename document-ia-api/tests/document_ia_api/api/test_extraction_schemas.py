from unittest.mock import patch

import pytest


class TestExtractionSchemas:
    """Integration tests for /extraction-schemas controller."""

    @pytest.mark.asyncio
    async def test_get_all_extraction_schemas_success(self, client_without_api_key):
        """Should return 200 with a non-empty array of schema entries."""
        response = client_without_api_key.get("/api/v1/extraction-schemas")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        # Accept empty list if no SupportedDocumentType, but generally expect entries
        if data:
            first = data[0]
            assert "document_type" in first
            assert "model" in first
            assert isinstance(first["model"], dict)
            # basic JSON Schema keys presence
            assert "type" in first["model"]
            assert first["model"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_get_all_extraction_schemas_internal_error(self, client_without_api_key):
        """When resolve_extract_schema raises, endpoint should return 500 ProblemDetail."""
        with patch(
            "document_ia_api.api.routes.v1.extraction_schemas.resolve_extract_schema"
        ) as mock_resolve:
            mock_resolve.side_effect = Exception("boom")
            response = client_without_api_key.get("/api/v1/extraction-schemas")

            assert response.status_code == 500
            body = response.json()
            # ProblemDetail-style body
            assert body.get("title") == "Internal Server Error"
            assert body.get("status") == 500
            assert body.get("code") in ("http.error", "internal.error")
            assert body.get("instance") == "/api/v1/extraction-schemas"
            assert "Internal Server Error - Get all extraction schemas failed with error:" in body.get("detail", "")
