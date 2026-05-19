from document_ia_infra.data.workflow.repository.workflow_v2_repository import (
    WorkflowV2Repository,
)


def test_can_instantiate_workflow_v2_repository():
    repository = WorkflowV2Repository()
    assert isinstance(repository, WorkflowV2Repository)
