from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.database import DatabaseManager
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.data.event.schema.event import WorkflowExecutionStartedEvent
from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_infra.s3.s3_manager import S3Manager

from document_ia_worker.workflow.workflow_manager import WorkflowManager

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
PDF_FIXTURE = FIXTURES_DIR / "test_download_file.pdf"


@pytest.mark.asyncio
async def test_workflow_extraction_end_to_end():
    # Preconditions
    assert PDF_FIXTURE.exists(), "Fixture PDF is missing"

    # Upload the PDF to S3
    s3 = S3Manager()
    content = PDF_FIXTURE.read_bytes()
    key = f"integration/workflow/{uuid4()}/test_download_file.pdf"
    s3.upload_file(file_key=key, file_data=content, content_type="application/pdf")

    # Prepare FileInfo and Started event
    execution_id = str(uuid4())
    workflow_id = "document-extraction-v1"
    file_info = FileInfo(
        filename=PDF_FIXTURE.name,
        s3_key=key,
        size=len(content),
        content_type="application/pdf",
        uploaded_at=datetime.now(timezone.utc).isoformat(),
        presigned_url="",
    )

    started_event = WorkflowExecutionStartedEvent(
        workflow_id=workflow_id,
        execution_id=execution_id,
        created_at=datetime.now(timezone.utc),
        version=1,
        file_info=file_info,
        metadata={"source": "integration-test"},
    ).model_dump(mode="json")

    dbm = DatabaseManager()
    async with dbm.local_session() as session:
        # Insert the started event
        repo = EventRepository(session)
        await repo.put_event(
            workflow_id=workflow_id,
            execution_id=execution_id,
            event_type=EventType.WORKFLOW_EXECUTION_STARTED,
            event_data=started_event,
        )
        await session.commit()

    # Execute the workflow
    message = WorkflowExecutionMessage(workflow_execution_id=execution_id)
    manager = WorkflowManager(message=message, retry_count=0)
    await manager.start()

    # Verify the last event is Completed and has expected payload
    async with dbm.local_session() as session:
        repo = EventRepository(session)
        last_event = await repo.get_last_event_by_execution_id(execution_id)
        assert last_event is not None, "No event found after workflow execution"
        assert (
            last_event.event_type == EventType.WORKFLOW_EXECUTION_COMPLETED
        ), f"Unexpected last event type: {last_event.event_type}"

        payload = last_event.event
        # Basic shape
        assert payload.get("workflow_id") == workflow_id
        assert payload.get("execution_id") == execution_id
        assert isinstance(payload.get("total_processing_time_ms"), int)
        # For extraction workflow: download, preprocess, ocr, llm_classify, llm_extract, save
        assert payload.get("steps_completed") == 6
        assert payload.get("version") == 1

        # Final result checks (extraction result)
        final_result = payload.get("final_result")
        assert isinstance(final_result, dict)
        # Should contain a type (classified document type) and a properties object
        assert final_result.get("classification").get("document_type", "").strip().lower() == "cni"
        props = final_result.get("extraction").get("properties")
        assert isinstance(props, dict)
        # Optionally check for some typical keys if present
        for key in ("numero_document", "nom", "prenom"):
            if key in props:
                assert isinstance(props[key], str)

    # Cleanup S3 object
    s3.delete_file(key)
