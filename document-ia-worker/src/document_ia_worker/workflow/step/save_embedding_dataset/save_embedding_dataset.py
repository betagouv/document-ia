import logging
from typing import Optional, Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.embedding.dto.document_template_embedding_dto import (
    DocumentTemplateEmbeddingDTO,
)
from document_ia_infra.data.embedding.repository.document_template_embedding_repository import (
    DocumentTemplateEmbeddingRepository,
)
from document_ia_worker.core.prompt.prompt_configuration import SupportedDocumentType
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepMetadata,
)
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.llm_result import (
    LLMClassificationResult,
    LLMEmbeddingResult,
)
from document_ia_worker.workflow.step.step_result.ocr_result import OcrResult

logger = logging.getLogger(__name__)


class SaveEmbeddingDatasetStep(BaseStep[None]):
    llm_embedding_result: Optional[LLMEmbeddingResult] = None
    anonymized_ocr_result: Optional[OcrResult] = None
    llm_classification_result: Optional[LLMClassificationResult] = None

    def __init__(
        self,
        main_workflow_context: MainWorkflowContext,
        database_session: AsyncSession,
    ):
        self.main_workflow_context = main_workflow_context
        self.execution_id = main_workflow_context.execution_id
        self.extraction_parameters = main_workflow_context.extraction_parameters
        self.database_session = database_session
        self.embedding_repository = DocumentTemplateEmbeddingRepository(
            self.database_session
        )

    def get_context_result_key(self) -> str:
        return ""

    async def _prepare_step(self):
        logger.info(
            "Preparing save embedding dataset step for execution: %s",
            self.execution_id,
        )
        if self.llm_embedding_result is None:
            raise ValueError("LLMEmbeddingResult not injected in context")
        if self.anonymized_ocr_result is None:
            raise ValueError("OcrResult not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        self.llm_embedding_result = self._get_safe_workflow_context_key(
            LLMEmbeddingResult, context
        )
        self.anonymized_ocr_result = self._get_safe_workflow_context_key(
            OcrResult, context
        )
        self.llm_classification_result = self._get_not_mandatory_workflow_context_key(
            LLMClassificationResult, context
        )

    async def _execute_internal(self) -> tuple[None, Optional[StepMetadata]]:
        assert self.llm_embedding_result is not None
        assert self.anonymized_ocr_result is not None

        document_type: Optional[SupportedDocumentType] = None
        if self.llm_classification_result is not None:
            document_type = SupportedDocumentType.from_str(
                self.llm_classification_result.data.document_type
            )
        elif (
            self.extraction_parameters is not None
            and self.extraction_parameters.document_type is not None
        ):
            document_type = self.extraction_parameters.document_type

        if document_type is None:
            raise ValueError("Document type could not be determined for embeddings")

        document_type_code = (
            document_type.value
            if hasattr(document_type, "value")
            else str(document_type)
        )

        pages = self.anonymized_ocr_result.pages
        embeddings_by_page = self.llm_embedding_result.embeddings_by_page

        if len(pages) != len(embeddings_by_page):
            raise ValueError("Embedding result does not match OCR page count")

        dtos: list[DocumentTemplateEmbeddingDTO] = []
        for index, page in enumerate(pages):
            embedding = embeddings_by_page[index]
            if page.text is None or page.text.strip() == "" or not embedding:
                continue

            dtos.append(
                DocumentTemplateEmbeddingDTO(
                    id=uuid4(),
                    document_type_code=document_type_code,
                    document_instance_id=self.execution_id,
                    page_number=page.page_number,
                    anonymized_text=page.text,
                    embedding=embedding,
                )
            )

        if not dtos:
            logger.info(
                "No embeddings to save for execution: %s",
                self.execution_id,
            )
            return None, None

        await self.embedding_repository.create_many(dtos)
        return None, None
