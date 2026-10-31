from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    ClassificationParameters,
    ExtractionParameters,
)
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_worker.exception.workflow_step_exception import WorkflowStepException
from document_ia_worker.workflow.workflow_manager import WorkflowManager


class TestWorkflowManager:
    @pytest.fixture
    def mock_workflow_message(self):
        return WorkflowExecutionMessage(workflow_execution_id="exec-12345")

    @pytest.fixture
    def mock_db_manager(self):
        with patch(
            "document_ia_worker.workflow.workflow_manager.DatabaseManager"
        ) as MockDBManager:
            mock_instance = MockDBManager.return_value
            mock_session = AsyncMock()

            # Setup async context manager for local_session
            mock_instance.local_session.return_value.__aenter__.return_value = (
                mock_session
            )
            mock_instance.local_session.return_value.__aexit__.return_value = None

            mock_instance.dispose_async = AsyncMock()
            yield MockDBManager

    @pytest.fixture
    def mock_dependencies(self):
        # Mocks for logging and context vars
        with (
            patch(
                "document_ia_worker.workflow.workflow_manager.setup_logging_worker"
            ) as mock_setup_log,
            patch(
                "document_ia_worker.workflow.workflow_manager.execution_id_var"
            ) as mock_exec_var,
            patch(
                "document_ia_worker.workflow.workflow_manager.agg_buffer_var"
            ) as mock_agg_var,
            patch(
                "document_ia_worker.workflow.workflow_manager.start_time_var"
            ) as mock_start_var,
            patch(
                "document_ia_worker.workflow.workflow_manager.handle_finish_execution"
            ) as mock_handle_finish,
            patch(
                "document_ia_worker.workflow.workflow_manager.Publisher"
            ) as mock_publisher,
            patch(
                "document_ia_worker.workflow.workflow_manager.RedisManager"
            ) as mock_redis_manager,
        ):
            mock_redis_manager.return_value.close = AsyncMock()
            mock_publisher_instance = mock_publisher.return_value
            mock_publisher_instance.publish_message = AsyncMock()

            yield {
                "setup_log": mock_setup_log,
                "exec_var": mock_exec_var,
                "agg_var": mock_agg_var,
                "start_var": mock_start_var,
                "handle_finish": mock_handle_finish,
                "publisher": mock_publisher_instance,
                "redis_manager": mock_redis_manager.return_value,
            }
            # Success, fatal/retryable failure, duplicates and cancellation
            # must all close the workflow-owned publisher manager.
            mock_redis_manager.return_value.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_success(
        self, mock_workflow_message, mock_db_manager, mock_dependencies
    ):
        """Test nominal : tout se passe bien."""

        manager = WorkflowManager(mock_workflow_message, retry_count=0)
        parsed_event = MagicMock(
            classification_parameters=ClassificationParameters(document_types=["cni"]),
            extraction_parameters=ExtractionParameters(document_type="cni"),
        )

        # Mock internal methods to simulate success without going into details
        # We want to test start() orchestration
        with (
            patch.object(
                manager, "_prepare_workflow", new_callable=AsyncMock
            ) as mock_prepare,
            patch.object(
                manager, "_parse_start_event", return_value=parsed_event
            ) as mock_parse,
            patch.object(manager, "_prepare_executor") as mock_prepare_exec,
            patch.object(
                manager, "_execute_workflow", new_callable=AsyncMock
            ) as mock_execute,
            patch.object(
                manager, "_notify_webhook_execution_finished", new_callable=AsyncMock
            ) as mock_notify,
            patch.object(
                manager, "_save_failure_event", new_callable=AsyncMock
            ) as mock_save_fail,
        ):
            await manager.start()

            # Verify orchestration
            mock_prepare.assert_called_once()
            mock_parse.assert_called_once()
            mock_prepare_exec.assert_called_once()
            mock_execute.assert_called_once()
            assert manager.main_workflow_context.classification_parameters is (
                parsed_event.classification_parameters
            )
            assert manager.main_workflow_context.extraction_parameters is (
                parsed_event.extraction_parameters
            )

            # Commit should be called
            mock_session = mock_db_manager.return_value.local_session.return_value.__aenter__.return_value
            mock_session.commit.assert_called_once()

            # Notify webhook called by default
            mock_notify.assert_called_once()

            # Handle finish execution
            mock_dependencies["handle_finish"].assert_called_once()
            args, _ = mock_dependencies["handle_finish"].call_args
            assert args[3] is True  # is_success
            assert args[9] is None  # err_type
            assert args[10] is None  # err_message
            assert args[11] is None  # failed_step

            # DB dispose
            mock_db_manager.return_value.dispose_async.assert_called_once()

            # No failure event
            mock_save_fail.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_generic_exception(
        self, mock_workflow_message, mock_db_manager, mock_dependencies
    ):
        """Test avec une exception générique non gérée (TypeError par ex)."""
        manager = WorkflowManager(mock_workflow_message, retry_count=0)

        with (
            patch.object(
                manager, "_prepare_workflow", side_effect=TypeError("Generic Error")
            ),
            patch.object(
                manager, "_save_failure_event", new_callable=AsyncMock
            ) as mock_save_fail,
            patch.object(
                manager, "_notify_webhook_execution_finished", new_callable=AsyncMock
            ) as mock_notify,
        ):
            with pytest.raises(TypeError, match="Generic Error"):
                await manager.start()

            # Verify failure handling
            # Should notify webhook (default behavior for generic error)
            mock_notify.assert_called_once()

            # Should save failure event
            mock_save_fail.assert_called_once()

            # Should handle finish execution with success=False
            mock_dependencies["handle_finish"].assert_called_once()
            args, _ = mock_dependencies["handle_finish"].call_args
            assert args[3] is False  # is_success
            assert args[9] == "TypeError"  # err_type
            assert args[10] == "Generic Error"  # err_message

            # DB should still be committed and disposed
            mock_session = mock_db_manager.return_value.local_session.return_value.__aenter__.return_value
            mock_session.commit.assert_called_once()
            mock_db_manager.return_value.dispose_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_workflow_step_exception_non_retryable(
        self, mock_workflow_message, mock_db_manager, mock_dependencies
    ):
        """Test avec une WorkflowStepException (non retryable inner exception)."""
        manager = WorkflowManager(mock_workflow_message, retry_count=0)

        inner_error = ValueError("Bad value")
        step_error = WorkflowStepException("step_x", inner_error)

        with (
            patch.object(manager, "_prepare_workflow", side_effect=step_error),
            patch.object(
                manager, "_save_failure_event", new_callable=AsyncMock
            ) as mock_save_fail,
            patch.object(
                manager, "_notify_webhook_execution_finished", new_callable=AsyncMock
            ) as mock_notify,
        ):
            # Should raise the inner exception
            with pytest.raises(ValueError, match="Bad value"):
                await manager.start()

            # Non-retryable -> notify webhook
            mock_notify.assert_called_once()

            # Save failure with inner details
            mock_save_fail.assert_called_once_with(
                mock_db_manager.return_value.local_session.return_value.__aenter__.return_value,
                step_error,
            )

            # Handle finish log
            mock_dependencies["handle_finish"].assert_called_once()

            args, _ = mock_dependencies["handle_finish"].call_args
            assert args[3] is False
            assert args[9] == "ValueError"
            assert args[11] == "step_x"  # failed_step

    @pytest.mark.asyncio
    async def test_start_workflow_step_exception_retryable_not_last_retry(
        self, mock_workflow_message, mock_db_manager, mock_dependencies
    ):
        """Test avec une WorkflowStepException retryable, et il reste des retries."""
        manager = WorkflowManager(
            mock_workflow_message, retry_count=0, is_last_retry=False
        )

        inner_error = RetryableException("Try again")
        step_error = WorkflowStepException("step_y", inner_error)

        with (
            patch.object(manager, "_prepare_workflow", side_effect=step_error),
            patch.object(
                manager, "_save_failure_event", new_callable=AsyncMock
            ) as mock_save_fail,
            patch.object(
                manager, "_notify_webhook_execution_finished", new_callable=AsyncMock
            ) as mock_notify,
        ):
            with pytest.raises(RetryableException, match="Try again"):
                await manager.start()

            # Retryable and NOT last retry -> NO webhook notification
            mock_notify.assert_not_called()

            mock_save_fail.assert_called_once()

            # Handle finish log
            mock_dependencies["handle_finish"].assert_called_once()
            args, _ = mock_dependencies["handle_finish"].call_args
            assert args[3] is False
            assert args[9] == "RetryableException"

    @pytest.mark.asyncio
    async def test_start_workflow_step_exception_retryable_is_last_retry(
        self, mock_workflow_message, mock_db_manager, mock_dependencies
    ):
        """Test avec une WorkflowStepException retryable, mais c'est le dernier retry."""
        manager = WorkflowManager(
            mock_workflow_message, retry_count=3, is_last_retry=True
        )

        inner_error = RetryableException("Give up")
        step_error = WorkflowStepException("step_z", inner_error)

        with (
            patch.object(manager, "_prepare_workflow", side_effect=step_error),
            patch.object(
                manager, "_save_failure_event", new_callable=AsyncMock
            ) as mock_save_fail,
            patch.object(
                manager, "_notify_webhook_execution_finished", new_callable=AsyncMock
            ) as mock_notify,
        ):
            with pytest.raises(RetryableException, match="Give up"):
                await manager.start()

            # Retryable BUT last retry -> notify webhook
            mock_notify.assert_called_once()

            mock_save_fail.assert_called_once()

            # Handle finish log
            mock_dependencies["handle_finish"].assert_called_once()

    @pytest.mark.asyncio
    async def test_completed_duplicate_returns_normally_without_execution(
        self, mock_workflow_message, mock_db_manager, mock_dependencies
    ):
        manager = WorkflowManager(mock_workflow_message, retry_count=0)
        repository = MagicMock()
        repository.get_created_event_if_execution_not_completed_or_failed = AsyncMock(
            return_value=None
        )
        repository.get_last_event_by_execution_id = AsyncMock(
            return_value=MagicMock(event_type=EventType.WORKFLOW_EXECUTION_COMPLETED)
        )

        with (
            patch(
                "document_ia_worker.workflow.workflow_manager.EventRepository",
                return_value=repository,
            ),
            patch.object(manager, "_parse_start_event") as mock_parse,
            patch.object(manager, "_prepare_executor") as mock_prepare_executor,
            patch.object(
                manager, "_execute_workflow", new_callable=AsyncMock
            ) as mock_execute,
            patch.object(
                manager, "_save_failure_event", new_callable=AsyncMock
            ) as mock_save_failure,
            patch.object(
                manager, "_notify_webhook_execution_finished", new_callable=AsyncMock
            ) as mock_notify,
        ):
            await manager.start()

        repository.get_created_event_if_execution_not_completed_or_failed.assert_awaited_once_with(
            "exec-12345"
        )
        repository.get_last_event_by_execution_id.assert_awaited_once_with("exec-12345")
        mock_parse.assert_not_called()
        mock_prepare_executor.assert_not_called()
        mock_execute.assert_not_awaited()
        mock_save_failure.assert_not_awaited()
        mock_notify.assert_not_awaited()
        mock_dependencies["handle_finish"].assert_not_called()
        mock_db_manager.return_value.dispose_async.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancellation_closes_workflow_owned_resources(
        self, mock_workflow_message, mock_db_manager, mock_dependencies
    ):
        import asyncio

        manager = WorkflowManager(mock_workflow_message, retry_count=0)
        executing = asyncio.Event()

        async def execute():
            executing.set()
            await asyncio.Event().wait()

        with (
            patch.object(
                manager, "_prepare_workflow", new=AsyncMock(return_value=False)
            ),
            patch.object(manager, "_parse_start_event", return_value=MagicMock()),
            patch.object(manager, "_prepare_executor"),
            patch.object(manager, "_execute_workflow", new=execute),
            patch.object(
                manager, "_notify_webhook_execution_finished", new=AsyncMock()
            ),
        ):
            task = asyncio.create_task(manager.start())
            await executing.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        mock_db_manager.return_value.dispose_async.assert_awaited_once()
        mock_dependencies["redis_manager"].close.assert_awaited_once()
