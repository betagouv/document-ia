import logging
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, Optional, cast

import yaml
from yaml.loader import SafeLoader
from yaml.nodes import ScalarNode

import document_ia_infra.data.workflow.dto.enums as infra_enums
import document_ia_schemas as schemas
from document_ia_infra.data.workflow.dto.workflow_v2_dto import WorkflowV2Dto

logger = logging.getLogger(__name__)

RawWorkflow = dict[str, Any]
RawStep = dict[str, Any]
RawRules = dict[str, Any]

MODULES_SOURCES: list[ModuleType] = [infra_enums, schemas]


def inject_constructor(_: SafeLoader, node: ScalarNode) -> Any:
    variable_name = node.value

    for module in MODULES_SOURCES:
        if hasattr(module, variable_name):
            obj = getattr(module, variable_name)

            if isinstance(obj, type) and issubclass(obj, Enum):
                return [item.value for item in obj]

            return cast(Any, obj)

    error_msg = (
        f"Impossible d'injecter '!inject {variable_name}' : introuvable dans "
        "infra_enums ni document_ia_schemas."
    )
    logger.error(error_msg)
    raise AttributeError(error_msg)


yaml.SafeLoader.add_constructor("!inject", inject_constructor)


def _extract_steps(raw_workflow: RawWorkflow) -> list[RawStep]:
    steps_raw = raw_workflow.get("steps")
    if not isinstance(steps_raw, list):
        return []
    steps_list = cast(list[Any], steps_raw)
    return [cast(RawStep, step) for step in steps_list if isinstance(step, dict)]


def _extract_params(step: RawStep) -> dict[str, RawRules]:
    params_raw = step.get("params")
    if not isinstance(params_raw, dict):
        return {}

    params: dict[str, RawRules] = {}
    params_map = cast(dict[Any, Any], params_raw)
    for param_name, rules in params_map.items():
        if isinstance(param_name, str) and isinstance(rules, dict):
            params[param_name] = cast(RawRules, rules)
    return params


def _generate_mock_payload(raw_workflow: RawWorkflow) -> RawWorkflow:
    mock_workflow: RawWorkflow = {
        "id": raw_workflow.get("id", ""),
        "name": raw_workflow.get("name", ""),
        "description": raw_workflow.get("description", ""),
        "version": raw_workflow.get("version", ""),
        "enabled": raw_workflow.get("enabled", True),
        "supported_file_types": raw_workflow.get("supported_file_types", []),
        "max_file_size_mb": raw_workflow.get("max_file_size_mb", 0),
        "processing_timeout_minutes": raw_workflow.get("processing_timeout_minutes", 0),
        "steps": [],
    }

    steps_out = cast(list[RawStep], mock_workflow["steps"])

    for step in _extract_steps(raw_workflow):
        action = step.get("action")
        mock_params: dict[str, Any] = {}

        for param_name, rules in _extract_params(step).items():
            if "default" in rules:
                mock_params[param_name] = rules["default"]
                continue

            enum_raw = rules.get("enum")
            if isinstance(enum_raw, list):
                enum_values = cast(list[Any], enum_raw)
                if enum_values:
                    mock_params[param_name] = enum_values[0]
                    continue

            if "oneOf" in rules:
                mock_params[param_name] = rules.get("default", "all")

        steps_out.append({"action": action, "params": mock_params})

    return mock_workflow


class WorkflowV2Repository:
    def __init__(self):
        current_dir = Path(__file__).parent
        data_package_dir = current_dir.parent
        self.workflows_file_path = data_package_dir / "data" / "workflows.yaml"

        # Keep both raw config and validated DTOs.
        self._raw_workflows: list[RawWorkflow] = []
        self._validated_workflows: list[WorkflowV2Dto] = []

        self._load_workflows()

    def _load_workflows(self) -> None:
        try:
            if not self.workflows_file_path.exists():
                logger.error(f"Fichier YAML introuvable : {self.workflows_file_path}")
                return

            with open(self.workflows_file_path, "r", encoding="utf-8") as stream:
                raw_yaml_data = yaml.safe_load(stream)

            if not isinstance(raw_yaml_data, dict):
                raise ValueError("Invalid workflows YAML root: expected mapping")

            yaml_map = cast(dict[str, Any], raw_yaml_data)
            workflows_raw = yaml_map.get("workflows")
            if not isinstance(workflows_raw, list):
                raise ValueError(
                    "Invalid workflows YAML structure: 'workflows' must be a list"
                )

            workflows_list = cast(list[Any], workflows_raw)
            self._raw_workflows = [
                cast(RawWorkflow, item)
                for item in workflows_list
                if isinstance(item, dict)
            ]

            self._validated_workflows = []
            for raw_workflow in self._raw_workflows:
                mock_payload = _generate_mock_payload(raw_workflow)
                validated_dto = WorkflowV2Dto.model_validate(mock_payload)
                self._validated_workflows.append(validated_dto)

            logger.info("%d workflows loaded and validated", len(self._raw_workflows))

        except Exception as exc:
            logger.error("Erreur de structure YAML lors du crash test : %s", exc)
            raise

    def get_raw_workflows(self) -> list[RawWorkflow]:
        return self._raw_workflows

    def get_raw_workflow_by_id(self, workflow_id: str) -> Optional[RawWorkflow]:
        for workflow in self._raw_workflows:
            if workflow.get("id") == workflow_id:
                return workflow
        return None


# Global workflow repository instance
workflow_v2_repository = WorkflowV2Repository()
