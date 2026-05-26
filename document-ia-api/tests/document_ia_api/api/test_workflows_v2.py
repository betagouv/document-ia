from unittest.mock import patch
from uuid import uuid4

import pytest
import json


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

    @pytest.mark.asyncio
    async def test_execute_workflow_v2_validates_override_success(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        override = {
            "llm_extract_data": [
                {"param": "document_type", "value": "cni"},
            ]
        }

        with patch(
            "document_ia_api.api.routes.v2.workflow.WorkflowV2Service.validateWorkflow"
        ) as mock_validate, patch(
            "document_ia_api.api.routes.v2.workflow.WorkflowV2Service.execute_workflow"
        ) as mock_execute:
            mock_validate.return_value = True
            mock_execute.return_value = {
                "execution_id": "exec_test",
                "workflow_id": "document-extraction-v2",
                "organization_id": str(uuid4()),
                "status": "processing",
                "created_at": "2026-05-26T10:30:00",
                "file_info": None,
                "file_url": "https://example.com/document.pdf",
                "metadata": {},
                "workflow_configuration": {
                    "id": "document-extraction-v2",
                    "name": "Document extraction v2 (Configurable)",
                    "description": "Workflow generique",
                    "version": "2.0.0",
                    "enabled": True,
                    "supported_file_types": ["application/pdf"],
                    "max_file_size_mb": 25,
                    "processing_timeout_minutes": 5,
                    "steps": [{"action": "download_file"}],
                },
            }

            response = client_with_api_key_standard.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                data={
                    "file_url": "https://example.com/document.pdf",
                    "override": json.dumps(override),
                },
                headers={"X-API-KEY": standard_api_key_value},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["execution_id"] == "exec_test"
        assert body["data"]["workflow_id"] == "document-extraction-v2"
        mock_validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_workflow_v2_invalid_param_returns_400(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        override = {
            "llm_extract_data": [
                {"param": "does_not_exist", "value": "x"},
            ]
        }

        response = client_with_api_key_standard.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={
                "file_url": "https://example.com/document.pdf",
                "override": json.dumps(override),
            },
            headers={"X-API-KEY": standard_api_key_value},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["status"] == 400
        assert body["errors"]["step"] == "llm_extract_data"
        assert body["errors"]["param"] == "does_not_exist"

    @pytest.mark.asyncio
    async def test_execute_workflow_v2_accepts_missing_override_field(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        with patch(
            "document_ia_api.api.routes.v2.workflow.WorkflowV2Service.validateWorkflow"
        ) as mock_validate, patch(
            "document_ia_api.api.routes.v2.workflow.WorkflowV2Service.execute_workflow"
        ) as mock_execute:
            mock_validate.return_value = True
            mock_execute.return_value = {
                "execution_id": "exec_defaults",
                "workflow_id": "document-defaults-v2",
                "organization_id": str(uuid4()),
                "status": "processing",
                "created_at": "2026-05-26T10:30:00",
                "file_info": None,
                "file_url": "https://example.com/document.pdf",
                "metadata": {},
                "workflow_configuration": {
                    "id": "document-defaults-v2",
                    "name": "Document defaults v2",
                    "description": "Workflow defaults",
                    "version": "2.0.0",
                    "enabled": True,
                    "supported_file_types": ["application/pdf"],
                    "max_file_size_mb": 25,
                    "processing_timeout_minutes": 5,
                    "steps": [{"action": "download_file"}],
                },
            }

            response = client_with_api_key_standard.post(
                "/api/v2/workflows/document-defaults-v2/execute",
                data={"file_url": "https://example.com/document.pdf"},
                headers={"X-API-KEY": standard_api_key_value},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["execution_id"] == "exec_defaults"
        assert body["data"]["workflow_id"] == "document-defaults-v2"
        _, kwargs = mock_execute.call_args
        assert kwargs["override_payload"].root == {}
        mock_validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_workflow_v2_returns_400_when_file_and_file_url_missing(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        response = client_with_api_key_standard.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={"override": json.dumps({})},
            headers={"X-API-KEY": standard_api_key_value},
        )

        assert response.status_code == 400
        assert response.json()["status"] == 400

    @pytest.mark.asyncio
    async def test_execute_workflow_v2_returns_400_when_file_and_file_url_both_provided(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        response = client_with_api_key_standard.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={"file_url": "https://example.com/document.pdf", "override": json.dumps({})},
            files={"file": ("doc.pdf", b"dummy", "application/pdf")},
            headers={"X-API-KEY": standard_api_key_value},
        )

        assert response.status_code == 400
        assert response.json()["status"] == 400

    @pytest.mark.asyncio
    async def test_execute_workflow_v2_returns_400_when_metadata_not_json_object(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        response = client_with_api_key_standard.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={
                "file_url": "https://example.com/document.pdf",
                "metadata": json.dumps(["not", "an", "object"]),
                "override": json.dumps({}),
            },
            headers={"X-API-KEY": standard_api_key_value},
        )

        assert response.status_code == 400
        assert response.json()["status"] == 400
