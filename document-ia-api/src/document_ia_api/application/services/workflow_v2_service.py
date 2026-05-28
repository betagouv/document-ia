import logging
import uuid
from datetime import datetime
from typing import Any, cast

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.contracts.workflow_v2 import WorkflowV2OverridePayload
from document_ia_api.api.exceptions.entity_not_found_exception import (
    HttpEntityNotFoundException,
)
from document_ia_api.core.file_validator import validate_uploaded_file
from document_ia_api.infra.s3_service import s3_service
from document_ia_api.schemas.workflow import WorkflowExecutionDataV2
from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.workflow.repository.workflow_v2_repository import (
    workflow_v2_repository,
)
from document_ia_infra.data.workflow.dto.workflow_v2_dto import WorkflowV2Dto
from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_infra.redis.publisher import Publisher
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.service.event_store_service import EventStoreService

logger = logging.getLogger(__name__)

RawWorkflow = dict[str, Any]
RawStep = dict[str, Any]
RawRule = dict[str, Any]


# noinspection PyUnnecessaryCast
class WorkflowV2Service:
    """Service dédié à la validation et à l'exécution des workflows v2."""

    def __init__(self, db_session: AsyncSession | None = None):
        self.db_session = db_session
        self.redis_producer = Publisher[WorkflowExecutionMessage](
            redis_settings.EVENT_STREAM_NAME
        )

    async def execute_workflow(
        self,
        organization_id: uuid.UUID,
        workflow_id: str,
        file: UploadFile | None,
        file_url: str | None,
        metadata_json: str | None,
        override_payload: WorkflowV2OverridePayload | None,
    ) -> WorkflowExecutionDataV2:
        if self.db_session is None:
            raise HTTPException(
                status_code=500,
                detail="WorkflowV2Service requires a database session for execution.",
            )

        # Raw workflow is needed here because override validation/resolution relies on YAML rules.
        raw_workflow = self._get_raw_workflow_or_404(workflow_id)

        resolved_workflow = self._resolve_workflow_configuration(
            raw_workflow=raw_workflow,
            override_payload=override_payload,
        )

        metadata = self._parse_metadata(metadata_json)
        execution_id = uuid.uuid4().__str__()

        file_info: FileInfo | None = None
        if file is not None:
            detected_mime_type = validate_uploaded_file(file)
            file_content = await self._read_file_content(file)
            s3_upload_result = await self._upload_file_to_s3(
                file_content=file_content,
                filename=file.filename,
                content_type=detected_mime_type,
                metadata=metadata,
            )

            file_info = FileInfo(
                filename=file.filename or "unknown",
                s3_key=s3_upload_result["s3_key"],
                size=len(file_content),
                content_type=detected_mime_type,
                uploaded_at=datetime.now().isoformat(),
                presigned_url=s3_upload_result["presigned_url"],
            )

        event_store_service = EventStoreService(self.db_session)
        await event_store_service.emit_workflow_started(
            workflow_id=workflow_id,
            execution_id=execution_id,
            organization_id=organization_id,
            file_info=file_info,
            file_url=file_url,
            metadata=metadata,
            workflow_configuration=resolved_workflow,
            event_version=2,
        )

        publish_id = await self.redis_producer.publish_message(
            WorkflowExecutionMessage(workflow_execution_id=execution_id)
        )
        if not publish_id:
            logger.warning(
                "Workflow v2 execution %s: message not published to stream %s",
                execution_id,
                self.redis_producer.stream_name,
            )

        return WorkflowExecutionDataV2(
            execution_id=execution_id,
            workflow_id=workflow_id,
            organization_id=organization_id,
            status="processing",
            created_at=datetime.now().isoformat(),
            file_info=file_info,
            file_url=file_url,
            metadata=metadata,
            workflow_configuration=resolved_workflow,
        )

    def validateWorkflow(
        self,
        workflow_id: str,
        override_payload: WorkflowV2OverridePayload | None = None,
    ) -> bool:
        """Validate workflow v2 override payload for execution.

        Returns True on success, otherwise raises HTTPException with step/param details.
        """

        raw_workflow = self._get_raw_workflow_or_404(workflow_id)

        workflow_steps_by_action: dict[str, RawStep] = {}
        for step in self._extract_steps(raw_workflow):
            action = step.get("action")
            if isinstance(action, str) and action:
                workflow_steps_by_action[action] = step

        override_by_step = override_payload.root if override_payload is not None else {}

        for step_name, step_overrides in override_by_step.items():
            step = workflow_steps_by_action.get(step_name)
            if step is None:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "workflow_validation_error",
                        "message": f"Step '{step_name}' not found in workflow '{workflow_id}'",
                        "step": step_name,
                        "param": None,
                    },
                )

            step_params_raw = step.get("params")
            step_params: RawRule = (
                cast(RawRule, step_params_raw)
                if isinstance(step_params_raw, dict)
                else {}
            )

            for param_override in step_overrides:
                param_name = param_override.param
                if param_name not in step_params:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "workflow_validation_error",
                            "message": f"Parameter '{param_name}' is not configurable for step '{step_name}'",
                            "step": step_name,
                            "param": param_name,
                        },
                    )

                self._validate_workflow_param_value(
                    step_name=step_name,
                    param_name=param_name,
                    rule=step_params[param_name],
                    value=param_override.value,
                )

        # Check required params (no default) are provided by YAML or override.
        for step_name, step in workflow_steps_by_action.items():
            step_params_raw = step.get("params")
            if not isinstance(step_params_raw, dict):
                continue
            step_params: RawRule = cast(RawRule, step_params_raw)

            step_override_names = {
                item.param for item in override_by_step.get(step_name, [])
            }

            for param_name, rule_obj in step_params.items():
                rule = rule_obj
                if not isinstance(rule, dict):
                    continue
                has_default = "default" in rule
                if not has_default and param_name not in step_override_names:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "workflow_validation_error",
                            "message": f"Missing required parameter '{param_name}' for step '{step_name}'",
                            "step": step_name,
                            "param": param_name,
                        },
                    )

        return True

    def _resolve_workflow_configuration(
        self,
        *,
        raw_workflow: dict[str, Any],
        override_payload: WorkflowV2OverridePayload | None,
    ) -> WorkflowV2Dto:
        override_by_step = override_payload.root if override_payload is not None else {}

        resolved_steps: list[dict[str, Any]] = []
        for step in self._extract_steps(raw_workflow):
            action = step.get("action")
            if not isinstance(action, str) or not action:
                continue
            params_raw = step.get("params")
            params: RawRule = (
                cast(RawRule, params_raw) if isinstance(params_raw, dict) else {}
            )
            override_map = {
                item.param: item.value for item in override_by_step.get(action, [])
            }

            resolved_params: dict[str, Any] = {}
            for param_name, rule in params.items():
                if param_name in override_map:
                    resolved_params[param_name] = override_map[param_name]
                    continue

                if isinstance(rule, dict) and "default" in rule:
                    resolved_params[param_name] = rule["default"]

            step_payload: dict[str, Any] = {"action": action}
            if resolved_params:
                step_payload["params"] = resolved_params
            resolved_steps.append(step_payload)

        workflow_id = (
            raw_workflow.get("id") if isinstance(raw_workflow.get("id"), str) else ""
        )
        workflow_name = (
            raw_workflow.get("name")
            if isinstance(raw_workflow.get("name"), str) and raw_workflow.get("name")
            else workflow_id
        )
        workflow_version = (
            raw_workflow.get("version")
            if isinstance(raw_workflow.get("version"), str)
            and raw_workflow.get("version")
            else "2"
        )

        resolved_workflow_payload = {
            "id": workflow_id,
            "name": workflow_name,
            "description": raw_workflow.get("description", ""),
            "version": workflow_version,
            "enabled": raw_workflow.get("enabled", True),
            "supported_file_types": raw_workflow.get("supported_file_types", []),
            "max_file_size_mb": raw_workflow.get("max_file_size_mb", 0),
            "processing_timeout_minutes": raw_workflow.get(
                "processing_timeout_minutes", 0
            ),
            "steps": resolved_steps,
        }

        try:
            return WorkflowV2Dto.model_validate(resolved_workflow_payload)
        except ValidationError as exc:
            logger.error(
                "Failed to resolve workflow configuration for workflow %s: %s",
                raw_workflow.get("id"),
                exc,
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "workflow_validation_error",
                    "message": "Resolved workflow configuration is invalid",
                },
            ) from exc

    @staticmethod
    def _parse_metadata(metadata_json: str | None) -> dict[str, Any]:
        if not metadata_json:
            return {}

        import json

        try:
            metadata = json.loads(metadata_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_metadata",
                    "message": f"Invalid JSON format in metadata: {str(exc)}",
                },
            ) from exc

        if not isinstance(metadata, dict):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_metadata",
                    "message": "Metadata must be a JSON object",
                },
            )

        return cast(dict[str, Any], metadata)

    @staticmethod
    async def _read_file_content(file: UploadFile) -> bytes:
        try:
            return await file.read()
        except Exception as exc:
            logger.error("Error reading file content: %s", exc)
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_read_error",
                    "message": "Failed to read uploaded file",
                },
            ) from exc

    @staticmethod
    async def _upload_file_to_s3(
        *,
        file_content: bytes,
        filename: str | None,
        content_type: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        import json

        try:
            s3_metadata = {
                "workflow_metadata": json.dumps(metadata),
                "upload_source": "workflow_v2_execution",
            }

            return await s3_service.upload_file(
                file_data=file_content,
                filename=filename,
                content_type=content_type,
                metadata=s3_metadata,
            )
        except Exception as exc:
            logger.error("S3 upload failed: %s", exc)
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "s3_upload_error",
                    "message": "Failed to upload file to storage",
                },
            ) from exc

    def _validate_workflow_param_value(
        self,
        *,
        step_name: str,
        param_name: str,
        rule: Any,
        value: Any,
    ) -> None:
        if not isinstance(rule, dict):
            return
        rule_dict: RawRule = cast(RawRule, rule)

        enum_values_raw = rule_dict.get("enum")
        enum_values = self._extract_str_list(enum_values_raw)
        if enum_values and value not in enum_values:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "workflow_validation_error",
                    "message": f"Invalid value for parameter '{param_name}' in step '{step_name}'",
                    "step": step_name,
                    "param": param_name,
                    "allowed_values": enum_values,
                },
            )

        one_of_raw = rule_dict.get("oneOf")
        one_of_variants: list[dict[str, Any]] = []
        if isinstance(one_of_raw, list):
            for variant in cast(list[Any], one_of_raw):
                if isinstance(variant, dict):
                    one_of_variants.append(cast(dict[str, Any], variant))
        if one_of_variants:
            if not any(
                self._matches_one_of_variant(variant=variant, value=value)
                for variant in one_of_variants
            ):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "workflow_validation_error",
                        "message": f"Invalid oneOf value for parameter '{param_name}' in step '{step_name}'",
                        "step": step_name,
                        "param": param_name,
                    },
                )
            return

        expected_type = rule_dict.get("type")
        if isinstance(expected_type, str) and not self._matches_simple_type(
            expected_type, value
        ):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "workflow_validation_error",
                    "message": f"Invalid type for parameter '{param_name}' in step '{step_name}'",
                    "step": step_name,
                    "param": param_name,
                    "expected_type": expected_type,
                },
            )

    def _matches_one_of_variant(self, *, variant: dict[str, Any], value: Any) -> bool:
        variant_type = variant.get("type")
        variant_enum_raw = variant.get("enum")
        variant_enum = self._extract_str_list(variant_enum_raw)

        if isinstance(variant_enum, list) and variant_enum and value in variant_enum:
            return True

        if variant_type == "array":
            if not isinstance(value, list):
                return False
            items_raw = variant.get("items")
            items = (
                cast(dict[str, Any], items_raw) if isinstance(items_raw, dict) else {}
            )
            items_enum_raw = items.get("enum")
            items_enum = self._extract_str_list(items_enum_raw)
            if items_enum is None:
                return True
            value_list = cast(list[Any], value)
            return all(item in items_enum for item in value_list)

        if isinstance(variant_type, str):
            return self._matches_simple_type(variant_type, value)

        return False

    @staticmethod
    def _matches_simple_type(expected_type: str, value: Any) -> bool:
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type in {"float", "number"}:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "object":
            return isinstance(value, dict)
        return True

    @staticmethod
    def _extract_steps(raw_workflow: RawWorkflow) -> list[RawStep]:
        steps_raw = raw_workflow.get("steps")
        if not isinstance(steps_raw, list):
            return []
        steps: list[RawStep] = []
        for step in cast(list[Any], steps_raw):
            if isinstance(step, dict):
                steps.append(cast(RawStep, step))
        return steps

    @staticmethod
    def _get_raw_workflow_or_404(workflow_id: str) -> RawWorkflow:
        raw_workflow = workflow_v2_repository.get_raw_workflow_by_id(workflow_id)
        if raw_workflow is None:
            raise HttpEntityNotFoundException(
                entity_name="workflow", entity_id=workflow_id
            )
        return raw_workflow

    @staticmethod
    def _extract_str_list(raw_value: Any) -> list[str] | None:
        if not isinstance(raw_value, list):
            return None
        raw_list = cast(list[Any], raw_value)
        values = [item for item in raw_list if isinstance(item, str)]
        if len(values) != len(raw_list):
            return None
        return values
