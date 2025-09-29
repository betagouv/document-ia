import json
import importlib.resources as resources
from typing import Dict, Any, List

import jinja2

from document_ia_worker.core.prompt.prompt_configuration import (
    PromptConfiguration,
    TaskType,
    SupportedDocumentType,
)


class PromptService:
    allowed_tasks: Dict[TaskType, PromptConfiguration]

    def __init__(self):
        # Use package resources to locate templates and schemas (no __file__/Path)
        # Templates live in the package subdirectory `prompts` and schemas in `schemas`.
        # jinja2.PackageLoader will load templates from the package resources.
        self.template_env = jinja2.Environment(
            loader=jinja2.PackageLoader("document_ia_worker.core.prompt", "prompts")
        )
        self.allowed_tasks = {
            TaskType.CLASSIFICATION: PromptConfiguration(
                task_type=TaskType.CLASSIFICATION,
            ),
        }

    def get_classification_prompt(
        self, document_type_list: list[SupportedDocumentType]
    ) -> str:
        prompt_template = self.template_env.get_template(
            self.allowed_tasks[TaskType.CLASSIFICATION].template_file
        )

        document_category_schema: List[Dict[str, Any]] = []
        for document_type in document_type_list:
            document_category_schema.append(
                self._load_schema_from_document_type(document_type)
            )

        return prompt_template.render(document_categories=document_category_schema)

    def _load_schema_from_document_type(
        self, document_type: SupportedDocumentType
    ) -> Dict[str, Any]:
        filename = f"document_{document_type.value}_schema.json"
        # Read schema JSON from package resources (schemas subpackage)
        with resources.open_text(
            "document_ia_worker.core.prompt.schemas", filename
        ) as file:
            return json.load(file)
