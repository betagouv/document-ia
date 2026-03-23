import json
import tempfile
from pathlib import Path

import pytest

from document_ia_infra.data.workflow.repository.workflow import WorkflowRepository


class TestWorkflowRepository:
    """Test cases for WorkflowRepository."""

    @pytest.fixture
    def sample_workflows_data(self):
        """Sample workflow data for testing."""
        return [
            {
                "id": "test-workflow-1",
                "name": "Test Workflow 1",
                "description": "A test workflow",
                "version": "1.0.0",
                "enabled": True,
                "steps": [
                    "download_file",
                    "preprocess_file",
                ],
                "type": "classification",
                "llm_model": "albert-large",
                "supported_file_types": ["application/pdf"],
                "max_file_size_mb": 10,
                "processing_timeout_minutes": 15,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": "test-workflow-2",
                "name": "Test Workflow 2",
                "description": "Another test workflow",
                "version": "1.0.0",
                "enabled": False,
                "steps": [
                    "download_file",
                    "preprocess_file",
                ],
                "type": "extraction",
                "llm_model": "albert-large",
                "supported_file_types": ["image/jpeg"],
                "max_file_size_mb": 5,
                "processing_timeout_minutes": 10,
                "created_at": "2024-01-02T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
            },
        ]

    @pytest.fixture
    def temp_workflows_file(self, sample_workflows_data):
        """Create a temporary workflows JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sample_workflows_data, f)
            temp_file_path = f.name

        yield temp_file_path

        # Cleanup
        Path(temp_file_path).unlink(missing_ok=True)

    @pytest.fixture
    def workflow_repository(self, temp_workflows_file):
        """Create a WorkflowRepository instance with temporary file."""
        return WorkflowRepository(workflows_file_path=temp_workflows_file)

    @pytest.mark.asyncio
    async def test_get_workflow_by_id_existing_enabled(self, workflow_repository):
        """Test retrieving an existing enabled workflow."""
        workflow = await workflow_repository.get_workflow_by_id("test-workflow-1")

        assert workflow is not None
        assert workflow.id == "test-workflow-1"
        assert workflow.name == "Test Workflow 1"
        assert workflow.enabled is True
        assert "application/pdf" in workflow.supported_file_types

    @pytest.mark.asyncio
    async def test_get_workflow_by_id_existing_disabled(self, workflow_repository):
        """Test retrieving an existing disabled workflow."""
        workflow = await workflow_repository.get_workflow_by_id("test-workflow-2")

        assert workflow is not None
        assert workflow.id == "test-workflow-2"
        assert workflow.name == "Test Workflow 2"
        assert workflow.enabled is False

    @pytest.mark.asyncio
    async def test_get_workflow_by_id_not_found(self, workflow_repository):
        """Test retrieving a non-existent workflow."""
        workflow = await workflow_repository.get_workflow_by_id("non-existent-workflow")

        assert workflow is None

    @pytest.mark.asyncio
    async def test_get_all_workflows(self, workflow_repository):
        """Test retrieving all workflows."""
        workflows = await workflow_repository.get_all_workflows()

        assert len(workflows) == 2
        workflow_ids = [w.id for w in workflows]
        assert "test-workflow-1" in workflow_ids
        assert "test-workflow-2" in workflow_ids

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        """Test behavior when workflows file doesn't exist."""
        repository = WorkflowRepository(workflows_file_path="/non/existent/path.json")

        with pytest.raises(FileNotFoundError):
            await repository.get_workflow_by_id("any-id")

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        """Test behavior with invalid JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json content")
            temp_file_path = f.name

        try:
            repository = WorkflowRepository(workflows_file_path=temp_file_path)

            with pytest.raises(json.JSONDecodeError):
                await repository.get_workflow_by_id("any-id")
        finally:
            Path(temp_file_path).unlink(missing_ok=True)
