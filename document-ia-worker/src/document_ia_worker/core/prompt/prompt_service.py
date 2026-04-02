import logging
from typing import Dict, Any, List, Tuple, Type, cast

import jinja2
from pydantic import BaseModel

from document_ia_schemas import BaseDocumentTypeSchema, resolve_extract_schema
from document_ia_schemas.utils.pydantic_utils import (
    extract_fields_info,
    build_response_format,
)
from document_ia_worker.core.prompt.prompt_configuration import (
    PromptConfiguration,
    TaskType,
    SupportedDocumentType,
)
from document_ia_worker.exception.unsupported_document_type import (
    UnsupportedDocumentType,
)

logger = logging.getLogger(__name__)


def _dict_to_bullets(value: Dict[str, Any]) -> str:
    """Render a dict as a Markdown bullet list: - **key**: value
    Values are stringified; missing/None become empty strings.
    """
    lines: List[str] = []
    for k, v in value.items():
        desc = "" if v is None else str(v)
        lines.append(f"- **{k}**: {desc}")
    return "\n".join(lines)


class PromptService:
    allowed_tasks: Dict[TaskType, PromptConfiguration]

    def __init__(self):
        # Use package resources to locate templates and schemas (no __file__/Path)
        # Templates live in the package subdirectory `prompts` and schemas in `schemas`.
        # jinja2.PackageLoader will load templates from the package resources.
        self.template_env = jinja2.Environment(
            loader=jinja2.PackageLoader("document_ia_worker.core.prompt", "prompts")
        )
        # Ensure JSON output keeps insertion order and preserves unicode (no \uXXXX)
        self.template_env.policies.setdefault("json.dumps_kwargs", {})
        self.template_env.policies["json.dumps_kwargs"].update(
            {
                "sort_keys": False,
                "ensure_ascii": False,
            }
        )
        # Register custom filters
        self.template_env.filters["dict_to_bullets"] = _dict_to_bullets

        self.allowed_tasks = {
            TaskType.CLASSIFICATION: PromptConfiguration(
                task_type=TaskType.CLASSIFICATION,
            ),
            TaskType.EXTRACTION: PromptConfiguration(
                task_type=TaskType.EXTRACTION,
            ),
        }

    def get_classification_prompt(
        self, document_type_list: list[SupportedDocumentType]
    ) -> str:
        prompt_template = self.template_env.get_template(
            self.allowed_tasks[TaskType.CLASSIFICATION].get_template_file()
        )

        document_category_schema: List[Dict[str, Any]] = []

        for document_type in document_type_list:
            try:
                schema_instance = self._get_schema_class_instance(document_type)
                document_category_schema.append(
                    schema_instance.get_document_description_dict()
                )
            except Exception as e:
                logger.error(
                    "DocumentSchema not found for %s not found: %s", document_type, e
                )
                raise UnsupportedDocumentType(document_type) from e

        return prompt_template.render(document_categories=document_category_schema)

    def get_extraction_prompt(
        self, document_type: SupportedDocumentType
    ) -> Tuple[str, Type[BaseModel]]:
        prompt_template = self.template_env.get_template(
            self.allowed_tasks[TaskType.EXTRACTION].get_template_file()
        )

        try:
            schema_instance = self._get_schema_class_instance(document_type)
            schema_dict = schema_instance.get_json_schema_dict()
            properties: dict[str, Any] = cast(
                dict[str, Any], schema_dict.get("properties")
            )
            defs: dict[str, Any] = cast(
                dict[str, Any],
                schema_dict.get("$defs", schema_dict.get("definitions", {})),
            )

            nested_fields_info: list[dict[str, Any]] = extract_fields_info(
                properties, defs
            )
            extraction_response_format: dict[str, Any] = build_response_format(
                properties, defs
            )

            extraction_examples: list[dict[str, Any]] = [
                example.model_dump(mode="json")
                for example in schema_instance.examples
            ]

            document_json_properties_with_description: Dict[str, str] = {
                key: value.get("description") for key, value in properties.items()
            }

            prompt_text = prompt_template.render(
                document_name=schema_instance.name,
                document_description=schema_instance.description,
                document_json_properties_with_description=document_json_properties_with_description,
                extraction_response_format=extraction_response_format,
                extraction_examples=extraction_examples,
                nested_fields_info=nested_fields_info,
            )

            return prompt_text, schema_instance.document_model

        except Exception as e:
            logger.error("DocumentSchema for %s not found: %s", document_type, e)
            raise UnsupportedDocumentType(document_type) from e

    def _get_schema_class_instance(
        self, document_type: SupportedDocumentType
    ) -> BaseDocumentTypeSchema[BaseModel]:
        try:
            return resolve_extract_schema(document_type.value)
        except ImportError as e:
            raise UnsupportedDocumentType(document_type) from e
