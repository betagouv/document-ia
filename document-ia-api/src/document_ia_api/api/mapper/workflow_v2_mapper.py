from typing import Any

from document_ia_api.api.contracts.workflow_v2 import (
    WorkflowV2RawItem,
    WorkflowV2ResponseItem,
    WorkflowV2StepParameterRuleRaw,
    WorkflowV2StepParameterRuleResponse,
    WorkflowV2StepResponse,
)


def _map_parameter_rule(
    rule: WorkflowV2StepParameterRuleRaw,
) -> WorkflowV2StepParameterRuleResponse:
    """Map raw YAML rule to API response rule with Swagger-like semantics.

    - simple type: expose a standard `type`
    - composite type: expose a clean `oneOf`
    """
    if rule.one_of:
        return WorkflowV2StepParameterRuleResponse(
            description=rule.description,
            default=rule.default,
            oneOf=rule.one_of,
        )

    return WorkflowV2StepParameterRuleResponse(
        description=rule.description,
        default=rule.default,
        type=rule.type,
        enum=rule.enum,
    )


def map_workflow_v2_raw_to_contract(
    workflow: WorkflowV2RawItem,
) -> WorkflowV2ResponseItem:
    mapped_steps: list[WorkflowV2StepResponse] = []
    for step in workflow.steps:
        mapped_params = None
        if step.params:
            mapped_params = {
                param_name: _map_parameter_rule(param_rule)
                for param_name, param_rule in step.params.items()
            }

        mapped_steps.append(
            WorkflowV2StepResponse(
                action=step.action,
                params=mapped_params,
            )
        )

    return WorkflowV2ResponseItem(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        version=workflow.version,
        enabled=workflow.enabled,
        supported_file_types=workflow.supported_file_types,
        max_file_size_mb=workflow.max_file_size_mb,
        processing_timeout_minutes=workflow.processing_timeout_minutes,
        steps=mapped_steps,
    )


def map_workflow_v2_raw_list_to_contract(
    workflows_raw: list[dict[str, Any]],
) -> list[WorkflowV2ResponseItem]:
    """Parse raw workflow dicts and map them to typed API contracts."""
    parsed_workflows = [
        WorkflowV2RawItem.model_validate(item) for item in workflows_raw
    ]
    return [map_workflow_v2_raw_to_contract(workflow) for workflow in parsed_workflows]
