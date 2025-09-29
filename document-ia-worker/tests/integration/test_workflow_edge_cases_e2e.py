from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.database import DatabaseManager
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.data.event.schema.event import WorkflowExecutionStartedEvent
from document_ia_infra.s3.s3_manager import S3Manager

from document_ia_worker.workflow.workflow_manager import WorkflowManager

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
PDF_FIXTURE = FIXTURES_DIR / "test_download_file.pdf"


def _s3_available() -> bool:
    try:
        return S3Manager().check_bucket_exists()
    except Exception:
        return False


class TestWorkflowEdgeCasesE2E:

    @pytest.mark.asyncio
    async def test_preprocess_without_download_fails(self, monkeypatch):
        """Workflow with only 'preprocess_file': missing DownloadFileReturnData must fail in PreprocessFileStep."""
        # Build a fake workflow definition (no S3 needed since no download step is run)
        wf_id = "wf-missing-download"
        fake_workflow = SimpleNamespace(id=wf_id, steps=["preprocess_file"], llm_model="albert-large")

        import document_ia_infra.data.workflow.repository.worflow as wf_repo_mod

        async def fake_get_workflow_by_id(_id: str):
            return fake_workflow if _id == wf_id else None

        monkeypatch.setattr(wf_repo_mod.workflow_repository, "get_workflow_by_id", fake_get_workflow_by_id)

        # Prepare a started event (FileInfo unused by this step but required by schema)
        execution_id = str(uuid4())
        file_info = FileInfo(
            filename=PDF_FIXTURE.name,
            s3_key="unused/key.pdf",
            size=123,
            content_type="application/pdf",
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            presigned_url="",
        )
        started_event = WorkflowExecutionStartedEvent(
            workflow_id=wf_id,
            execution_id=execution_id,
            created_at=datetime.now(timezone.utc),
            version=1,
            file_info=file_info,
            metadata={"source": "edge-test"},
        ).model_dump(mode="json")

        dbm = DatabaseManager()
        async with dbm.local_session() as session:
            repo = EventRepository(session)
            await repo.put_event(
                workflow_id=wf_id,
                execution_id=execution_id,
                event_type=EventType.WORKFLOW_EXECUTION_STARTED,
                event_data=started_event,
            )
            await session.commit()

        # Run manager
        manager = WorkflowManager(message=SimpleNamespace(workflow_execution_id=execution_id), retry_count=0)
        with pytest.raises(ValueError):
            await manager.start()

        # Assert failed event
        async with dbm.local_session() as session:
            repo = EventRepository(session)
            last_event = await repo.get_last_event_by_execution_id(execution_id)
            assert last_event is not None
            assert last_event.event_type == EventType.WORKFLOW_EXECUTION_FAILED
            payload = last_event.event
            assert payload.get("failed_step") == "PreprocessFileStep"
            assert payload.get("error_type") in ("ValueError", "Exception")
            # message comes from step: "DownloadFileReturnData not injected in context"
            assert "not injected" in payload.get("error_message", "") or "not found" in payload.get("error_message", "")
            assert payload.get("retry_count") == 0

    @pytest.mark.asyncio
    async def test_ocr_without_preprocess_fails(self, monkeypatch):
        """Workflow 'download_file' then 'extract_content_ocr' without preprocess must fail in ExtractContentOcrStep."""
        if not _s3_available():
            pytest.skip("S3 not available; skipping test")
        assert PDF_FIXTURE.exists(), "Fixture PDF is missing"

        wf_id = "wf-missing-preprocess"
        fake_workflow = SimpleNamespace(id=wf_id, steps=["download_file", "extract_content_ocr"],
                                        llm_model="albert-large")

        import document_ia_infra.data.workflow.repository.worflow as wf_repo_mod

        async def fake_get_workflow_by_id(_id: str):  # noqa: ANN001
            return fake_workflow if _id == wf_id else None

        monkeypatch.setattr(wf_repo_mod.workflow_repository, "get_workflow_by_id", fake_get_workflow_by_id)

        # Upload file to S3 for the download step
        s3 = S3Manager()
        content = PDF_FIXTURE.read_bytes()
        key = f"integration/edge/{uuid4()}/test_download_file.pdf"
        s3.upload_file(file_key=key, file_data=content, content_type="application/pdf")

        execution_id = str(uuid4())
        file_info = FileInfo(
            filename=PDF_FIXTURE.name,
            s3_key=key,
            size=len(content),
            content_type="application/pdf",
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            presigned_url="",
        )
        started_event = WorkflowExecutionStartedEvent(
            workflow_id=wf_id,
            execution_id=execution_id,
            created_at=datetime.now(timezone.utc),
            version=1,
            file_info=file_info,
            metadata={"source": "edge-test"},
        ).model_dump(mode="json")

        dbm = DatabaseManager()
        async with dbm.local_session() as session:
            repo = EventRepository(session)
            await repo.put_event(
                workflow_id=wf_id,
                execution_id=execution_id,
                event_type=EventType.WORKFLOW_EXECUTION_STARTED,
                event_data=started_event,
            )
            await session.commit()

        manager = WorkflowManager(message=SimpleNamespace(workflow_execution_id=execution_id), retry_count=0)
        with pytest.raises(ValueError):
            await manager.start()

        async with dbm.local_session() as session:
            repo = EventRepository(session)
            last_event = await repo.get_last_event_by_execution_id(execution_id)
            assert last_event is not None
            assert last_event.event_type == EventType.WORKFLOW_EXECUTION_FAILED
            payload = last_event.event
            assert payload.get("failed_step") == "ExtractContentOcrStep"
            assert payload.get("error_type") in ("ValueError", "Exception")
            assert "not" in payload.get("error_message", "").lower()
            assert payload.get("retry_count") == 0

        # cleanup S3
        s3.delete_file(key)

    @pytest.mark.asyncio
    async def test_save_results_without_llm_fails(self, monkeypatch):
        """Workflow with only 'save_results': missing LLMResult must fail in SaveWorkflowResultStep."""
        wf_id = "wf-missing-llm"
        fake_workflow = SimpleNamespace(id=wf_id, steps=["save_results"], llm_model="albert-large")

        import document_ia_infra.data.workflow.repository.worflow as wf_repo_mod

        async def fake_get_workflow_by_id(_id: str):  # noqa: ANN001
            return fake_workflow if _id == wf_id else None

        monkeypatch.setattr(wf_repo_mod.workflow_repository, "get_workflow_by_id", fake_get_workflow_by_id)

        execution_id = str(uuid4())
        # FileInfo still required by schema
        file_info = FileInfo(
            filename=PDF_FIXTURE.name,
            s3_key="unused/key.pdf",
            size=123,
            content_type="application/pdf",
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            presigned_url="",
        )
        started_event = WorkflowExecutionStartedEvent(
            workflow_id=wf_id,
            execution_id=execution_id,
            created_at=datetime.now(timezone.utc),
            version=1,
            file_info=file_info,
            metadata={"source": "edge-test"},
        ).model_dump(mode="json")

        dbm = DatabaseManager()
        async with dbm.local_session() as session:
            repo = EventRepository(session)
            await repo.put_event(
                workflow_id=wf_id,
                execution_id=execution_id,
                event_type=EventType.WORKFLOW_EXECUTION_STARTED,
                event_data=started_event,
            )
            await session.commit()

        manager = WorkflowManager(message=SimpleNamespace(workflow_execution_id=execution_id), retry_count=0)
        with pytest.raises(ValueError):
            await manager.start()

        async with dbm.local_session() as session:
            repo = EventRepository(session)
            last_event = await repo.get_last_event_by_execution_id(execution_id)
            assert last_event is not None
            assert last_event.event_type == EventType.WORKFLOW_EXECUTION_FAILED
            payload = last_event.event
            assert payload.get("failed_step") == "SaveWorkflowResultStep"
            assert payload.get("error_type") in ("ValueError", "Exception")
            assert "not" in payload.get("error_message", "").lower()
            assert payload.get("retry_count") == 0
