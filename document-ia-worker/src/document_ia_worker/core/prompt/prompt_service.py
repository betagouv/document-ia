import json
import importlib.resources as resources
import logging
import importlib
import inspect
from pathlib import PosixPath
from typing import Dict, Any, List, Tuple, Type, cast

import jinja2
from pydantic import BaseModel

from document_ia_worker.core.prompt.prompt_configuration import (
    PromptConfiguration,
    TaskType,
    SupportedDocumentType,
)
from document_ia_worker.exception.unsupported_document_type import (
    UnsupportedDocumentType,
)

logger = logging.getLogger(__name__)


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
                document_category_schema.append(
                    self._load_schema_from_document_type(document_type)
                )
            except Exception as e:
                logger.error("Schema for %s not found: %s", document_type, e)
                raise UnsupportedDocumentType(document_type) from e

        return prompt_template.render(document_categories=document_category_schema)

    def get_extraction_prompt(
        self, document_type_str: str
    ) -> Tuple[str, Type[BaseModel]]:
        """Return a tuple (prompt_text, response_model_class) for the given document type string.

        The method will:
        - resolve SupportedDocumentType from the string
        - load the JSON schema from the package `document_type.<type>.schema`
        - discover the extract model module inside `document_type.<type>.model` (first *_extract.py or first .py)
        - import that module and return the first BaseModel subclass defined there

        Raises UnsupportedDocumentType when resolution/import fails.
        """
        try:
            document_type = SupportedDocumentType.from_str(document_type_str)
        except ValueError as e:
            logger.error("Unknown document type: %s", document_type_str)
            raise UnsupportedDocumentType(document_type_str) from e

        # Load JSON schema (file named "schema.json" in package document_type.<type>.schema)
        try:
            json_schema = self._load_schema_from_document_type(document_type)
        except FileNotFoundError as e:
            logger.error("Schema for %s not found: %s", document_type_str, e)
            raise UnsupportedDocumentType(document_type_str) from e

        extraction_model_type = self._get_extraction_type(document_type)

        # Render a template if one exists for extraction, otherwise return empty prompt
        # Template convention: extraction_agent_system_prompt.md.j2
        prompt_template = self.template_env.get_template(
            self.allowed_tasks[TaskType.EXTRACTION].get_template_file()
        )
        prompt_text = prompt_template.render(
            document_name=json_schema["name"],
            document_description=json_schema["description"],
            document_json_properties=json_schema["json_schema"]["properties"],
        )

        return prompt_text, extraction_model_type

    def _get_extraction_type(
        self, document_type: SupportedDocumentType
    ) -> Type[BaseModel]:
        # Discover model module in document_type.<type>.model
        model_pkg = (
            f"document_ia_worker.core.prompt.document_type.{document_type.value}.model"
        )
        try:
            pkg_files = resources.files(model_pkg)
        except Exception as e:
            logger.error("Model package not found for %s: %s", document_type, e)
            raise UnsupportedDocumentType(document_type) from e

        # Pick a candidate module: prefer files matching *_extract.py, otherwise first .py
        candidate_name: str | None = None
        for entry in pkg_files.iterdir():
            posix_entry = cast(PosixPath, entry)
            if not posix_entry.name.endswith(".py"):
                continue
            if posix_entry.name == "__init__.py":
                continue
            if posix_entry.name.endswith("_extract.py"):
                candidate_name = posix_entry.stem
                break
            if candidate_name is None:
                candidate_name = posix_entry.stem

        if candidate_name is None:
            logger.error("No model module found in %s", model_pkg)
            raise UnsupportedDocumentType(document_type)

        module_name = f"{model_pkg}.{candidate_name}"
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            logger.error("Failed to import model module %s: %s", module_name, e)
            raise UnsupportedDocumentType(document_type) from e

        # Find the first class defined in the module that is a subclass of pydantic.BaseModel
        model_class: Type[BaseModel] | None = None
        for _, obj in inspect.getmembers(module, inspect.isclass):
            # ensure class is defined in that module to avoid picking imported classes
            if obj.__module__ != module.__name__:
                continue
            try:
                if issubclass(obj, BaseModel):
                    model_class = obj
                    break
            except TypeError:
                # obj is likely not a class we can check
                continue

        if model_class is None:
            logger.error("No BaseModel subclass found in module %s", module_name)
            raise UnsupportedDocumentType(document_type)

        return model_class

    def _load_schema_from_document_type(
        self, document_type: SupportedDocumentType
    ) -> Dict[str, Any]:
        filename = "schema.json"
        # Read schema JSON from package resources (each document_type has its own schema package)
        pkg = (
            f"document_ia_worker.core.prompt.document_type.{document_type.value}.schema"
        )
        with resources.open_text(pkg, filename) as file:
            return json.load(file)
