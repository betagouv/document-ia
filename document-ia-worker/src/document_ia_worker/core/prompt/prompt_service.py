import json
import os.path
from pathlib import Path
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
        # Resolve directories relative to this file to avoid CWD issues
        base_dir = Path(__file__).resolve().parent  # .../core/prompt
        self.prompts_directory = base_dir / "prompts"
        self.schemas_directory = base_dir / "schemas"

        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(searchpath=str(self.prompts_directory))
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
        schema_path = os.path.join(
            self.schemas_directory, f"document_{document_type.value}_schema.json"
        )
        with open(schema_path, "r") as file:
            return json.load(file)
