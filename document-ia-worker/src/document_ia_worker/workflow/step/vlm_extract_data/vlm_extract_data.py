import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from document_ia_infra.data.document.schema.document_classification import (
    DocumentClassification,
)
from document_ia_infra.data.document.schema.document_extraction import (
    DocumentExtraction,
)
from document_ia_infra.data.workflow.dto.workflow_v2_dto import VLMExtractParams
from document_ia_infra.exception.openai_authentification_error import (
    OpenAIAuthentificationError,
)
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.openai.openai_manager import OpenAIManager
from document_ia_schemas import SupportedDocumentType

from document_ia_worker.core.prompt.prompt_configuration import (
    GENERIC_CLASSIFICATION_MODEL,
)
from document_ia_worker.core.prompt.prompt_service import PromptService
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepLLMMetadata,
)
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)
from document_ia_worker.workflow.step.step_result.llm_result import (
    VLMExtractionResult,
)

logger = logging.getLogger(__name__)


OCR_PROMPT = """
Effectue l'OCR complet du document fourni.

Retourne uniquement le texte lu, sans commentaire, sans Markdown et sans
interprétation. Respecte autant que possible la mise en page, les retours à la
ligne et les caractères spéciaux visibles sur le document.
""".strip()

VLM_SYSTEM_PROMPT = (
    "Tu es un assistant multimodal spécialisé dans l'analyse de documents. "
    "Suis précisément les instructions de chaque demande et réponds dans le "
    "format demandé."
)

VLM_CNI_MRZ_INSTRUCTION = """
## Instruction spécifique de lecture de la zone MRZ de la CNI

Pour le champ `bande_mrz`, accorde une attention particulière à la lecture de
chaque caractère de la zone MRZ. Utilise à la fois le texte OCR déjà fourni et
les images originales du document présentes au début de cette conversation.

En particulier, ne supprime jamais le dernier chiffre d'une séquence de
caractères `<`. Un motif fréquent est par exemple `<<<<<<<<<<4` : le `4` est
la clé de contrôle et il fait partie intégrante de la MRZ. Ce chiffre disparaît
souvent de l'OCR ; relis alors directement la zone MRZ sur l'image pour vérifier
et restituer la chaîne complète, caractère par caractère. N'invente jamais une
clé de contrôle : si le caractère reste réellement illisible après comparaison
de l'OCR et de l'image, utilise `null` conformément aux instructions générales.
""".strip()


class EmptyExtractionProperties(BaseModel):
    pass


def _image_content(file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
    }


class VLMExtractDataStep(BaseStep[VLMExtractionResult]):
    preprocess_file_result: PreprocessFileResult | None = None

    def __init__(
        self,
        main_workflow_context: MainWorkflowContext,
        params: VLMExtractParams,
    ):
        self.execution_id = main_workflow_context.execution_id
        self.model = params.model.value
        self.temperature = params.temperature
        self.document_types = (
            list(params.document_types)
            if params.document_types != "all"
            else GENERIC_CLASSIFICATION_MODEL
        )
        self.openai_manager = OpenAIManager()
        self.prompt_service = PromptService()

    def get_context_result_key(self) -> str:
        return VLMExtractionResult.__name__

    def inject_workflow_context(self, context: dict[str, Any]):
        self.preprocess_file_result = self._get_safe_workflow_context_key(
            PreprocessFileResult, context
        )

    async def _prepare_step(self):
        if self.preprocess_file_result is None:
            raise ValueError("PreprocessFileResult not injected in context")

    async def _call(self, messages: list[dict[str, Any]]) -> tuple[str, int, int]:
        try:
            return await self.openai_manager.get_vlm_response(
                messages=messages,
                model=self.model,
                temperature=self.temperature,
            )
        except OpenAIAuthentificationError as e:
            raise RetryableException(e.message)

    async def _call_typed(
        self,
        messages: list[dict[str, Any]],
        response_class: type[BaseModel],
    ) -> tuple[BaseModel, str, int, int]:
        try:
            return await self.openai_manager.get_vlm_typed_response(
                messages=messages,
                response_class=response_class,
                model=self.model,
                temperature=self.temperature,
            )
        except OpenAIAuthentificationError as e:
            raise RetryableException(e.message)

    async def _execute_internal(self) -> tuple[VLMExtractionResult, StepLLMMetadata]:
        assert self.preprocess_file_result is not None
        if not self.preprocess_file_result.output_files_path:
            raise ValueError("No preprocessed document image found")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": VLM_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    *(
                        _image_content(file_path)
                        for file_path in self.preprocess_file_result.output_files_path
                    ),
                ],
            }
        ]

        ocr_response, request_tokens, response_tokens = await self._call(messages)
        messages.append({"role": "assistant", "content": ocr_response})

        classification_prompt = self.prompt_service.get_classification_prompt(
            self.document_types
        )
        messages.append({"role": "user", "content": classification_prompt})
        classification, classification_response, request_tokens_2, response_tokens_2 = (
            await self._call_typed(messages, DocumentClassification)
        )
        messages.append({"role": "assistant", "content": classification_response})
        classification = cast(DocumentClassification, classification)

        document_type = SupportedDocumentType.from_str(classification.document_type)
        request_tokens_3 = 0
        response_tokens_3 = 0
        if document_type == SupportedDocumentType.AUTRE:
            extraction = cast(
                DocumentExtraction[BaseModel],
                DocumentExtraction[EmptyExtractionProperties](
                    type=document_type,
                    properties=EmptyExtractionProperties(),
                ),
            )
        else:
            extraction_prompt, extraction_class = self.prompt_service.get_extraction_prompt(
                document_type
            )
            if document_type == SupportedDocumentType.CNI:
                extraction_prompt = (
                    f"{extraction_prompt}\n\n{VLM_CNI_MRZ_INSTRUCTION}"
                )
            messages.append({"role": "user", "content": extraction_prompt})
            extraction_response_obj, extraction_response, request_tokens_3, response_tokens_3 = (
                await self._call_typed(messages, extraction_class)
            )
            messages.append({"role": "assistant", "content": extraction_response})
            extraction = DocumentExtraction(
                type=document_type,
                properties=extraction_response_obj,
            )

        return (
            VLMExtractionResult(
                classification=classification,
                extraction=extraction,
            ),
            StepLLMMetadata(
                step_name=self.__class__.__name__,
                request_tokens=request_tokens
                + request_tokens_2
                + (request_tokens_3 if document_type != SupportedDocumentType.AUTRE else 0),
                response_tokens=response_tokens
                + response_tokens_2
                + (response_tokens_3 if document_type != SupportedDocumentType.AUTRE else 0),
                model=self.model,
            ),
        )
