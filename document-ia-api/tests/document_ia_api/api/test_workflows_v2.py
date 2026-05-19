from unittest.mock import patch
from uuid import uuid4

import pytest


class TestWorkflowsV2:
    @pytest.fixture
    async def organization_id(self):
        # Local override to keep route tests independent from a live DB.
        yield uuid4()

    @pytest.mark.asyncio
    async def test_list_available_workflows_success(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        mocked_workflows = [
            {
                "id": "document-extraction-v2",
                "name": "Document extraction v2 (Configurable)",
                "description": "Workflow generique",
                "version": "2.0.0",
                "enabled": True,
                "supported_file_types": ["application/pdf"],
                "max_file_size_mb": 25,
                "processing_timeout_minutes": 5,
                "steps": [{"action": "download_file"}],
            }
        ]

        with patch(
            "document_ia_api.api.routes.v2.workflow.workflow_v2_repository.get_raw_workflows"
        ) as mock_get:
            mock_get.return_value = mocked_workflows

            response = client_with_api_key_standard.get(
                "/api/v2/workflows/",
                headers={"X-API-KEY": standard_api_key_value},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["message"] == "Available workflows retrieved successfully"
        assert isinstance(body["data"], list)
        assert body["data"][0]["id"] == "document-extraction-v2"

    @pytest.mark.asyncio
    async def test_list_available_workflows_internal_error(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        with patch(
            "document_ia_api.api.routes.v2.workflow.workflow_v2_repository.get_raw_workflows"
        ) as mock_get:
            mock_get.side_effect = Exception("boom")

            response = client_with_api_key_standard.get(
                "/api/v2/workflows/",
                headers={"X-API-KEY": standard_api_key_value},
            )

        assert response.status_code == 500
        body = response.json()
        assert body.get("title") == "Internal Server Error"
        assert body.get("status") == 500

    @pytest.mark.asyncio
    async def test_list_available_workflows_simplifies_document_types_rule(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        mocked_workflows = [
            {
                "id": "document-classification-extraction-v2",
                "name": "Workflow test",
                "description": "Workflow test",
                "version": "2.0.0",
                "enabled": True,
                "supported_file_types": ["application/pdf"],
                "max_file_size_mb": 25,
                "processing_timeout_minutes": 5,
                "steps": [
                    {
                        "action": "llm_classify_document",
                        "params": {
                            "document_types": {
                                "description": "Type(s) de document à utiliser pour la classification.",
                                "default": "all",
                                "oneOf": [
                                    {"type": "string", "enum": ["all"]},
                                    {
                                        "type": "array",
                                        "items": {
                                            "type": "string",
                                            "enum": ["cni", "passeport"],
                                        },
                                    },
                                ],
                            }
                        },
                    }
                ],
            }
        ]

        with patch(
            "document_ia_api.api.routes.v2.workflow.workflow_v2_repository.get_raw_workflows"
        ) as mock_get:
            mock_get.return_value = mocked_workflows

            response = client_with_api_key_standard.get(
                "/api/v2/workflows/",
                headers={"X-API-KEY": standard_api_key_value},
            )

        assert response.status_code == 200
        body = response.json()
        rule = body["data"][0]["steps"][0]["params"]["document_types"]
        assert "type" not in rule
        assert rule["default"] == "all"
        assert "oneOf" in rule
        assert rule["oneOf"] == [
            {"type": "string", "enum": ["all"]},
            {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["cni", "passeport"],
                },
            },
        ]
