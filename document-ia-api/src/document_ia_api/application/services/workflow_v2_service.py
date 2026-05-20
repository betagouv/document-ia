import logging
from typing import Any

from fastapi import HTTPException

from document_ia_api.api.contracts.workflow_v2 import WorkflowV2OverridePayload
from document_ia_api.api.exceptions.entity_not_found_exception import (
    HttpEntityNotFoundException,
)
from document_ia_infra.data.workflow.repository.workflow_v2_repository import (
    workflow_v2_repository,
)

logger = logging.getLogger(__name__)


class WorkflowV2Service:
    """Service dédié à la validation et à l'exécution des workflows v2."""

    def validateWorkflow(
        self,
        workflow_id: str,
        override_payload: WorkflowV2OverridePayload | None = None,
    ) -> bool:
        """Validate workflow v2 override payload for execution.

        Returns True on success, otherwise raises HTTPException with step/param details.
        """

        raw_workflow = workflow_v2_repository.get_raw_workflow_by_id(workflow_id)
        if raw_workflow is None:
            raise HttpEntityNotFoundException(
                entity_name="workflow", entity_id=workflow_id
            )

        steps = raw_workflow.get("steps", [])
        workflow_steps_by_action: dict[str, dict[str, Any]] = {}
        for step in steps:
            if not isinstance(step, dict):
                continue
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

            step_params = step.get("params") or {}
            if not isinstance(step_params, dict):
                step_params = {}

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
            step_params = step.get("params") or {}
            if not isinstance(step_params, dict):
                continue

            step_override_names = {
                item.param for item in override_by_step.get(step_name, [])
            }

            for param_name, rule in step_params.items():
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

        enum_values = rule.get("enum")
        if isinstance(enum_values, list) and enum_values and value not in enum_values:
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

        one_of = rule.get("oneOf")
        if isinstance(one_of, list) and one_of:
            if not any(
                self._matches_one_of_variant(variant=variant, value=value)
                for variant in one_of
                if isinstance(variant, dict)
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

        expected_type = rule.get("type")
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

    def _matches_one_of_variant(self, *, variant: dict, value: Any) -> bool:
        variant_type = variant.get("type")
        variant_enum = variant.get("enum")

        if isinstance(variant_enum, list) and variant_enum and value in variant_enum:
            return True

        if variant_type == "array":
            if not isinstance(value, list):
                return False
            items = (
                variant.get("items") if isinstance(variant.get("items"), dict) else {}
            )
            items_enum = (
                items.get("enum") if isinstance(items.get("enum"), list) else None
            )
            if items_enum is None:
                return True
            return all(item in items_enum for item in value)

        if isinstance(variant_type, str):
            return self._matches_simple_type(variant_type, value)

        return False

    def _matches_simple_type(self, expected_type: str, value: Any) -> bool:
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
