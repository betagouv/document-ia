import logging
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.core.ocr_type import OCRType
from document_ia_infra.data.document.schema.document_classification import (
    DocumentClassification,
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


class EmbeddingClassifyDocumentStep(BaseStep[LLMClassificationResult]):
    """Classifie un document par similarité d'embedding.

    Stratégie en base:
    - Pour chaque page avec embedding, requête pgvector top_k en filtrant par page_number.
    - Agrège tous les candidats et conserve les 5 meilleurs globalement.

    Sélection de catégorie:
    - Filtre les candidats sous le seuil min_similarity (par défaut 0.70).
    - Vote majoritaire sur les catégories restantes.
    - Si majorité stricte -> catégorie gagnante, sinon AUTRE.
    """

    llm_embedding_result: Optional[LLMEmbeddingResult] = None
    ocr_result: Optional[OcrResult] = None

    def __init__(
        self,
        main_workflow_context: MainWorkflowContext,
        database_session: AsyncSession,
        *,
        min_similarity: float = 0.7,
        top_k: int = 5,
    ):
        self.execution_id = main_workflow_context.execution_id
        self.extraction_parameters = main_workflow_context.extraction_parameters
        self.classification_parameters = main_workflow_context.classification_parameters
        self.database_session = database_session
        self.embedding_repository = DocumentTemplateEmbeddingRepository(
            self.database_session
        )
        self.min_similarity = min_similarity
        self.top_k = top_k

    def get_context_result_key(self) -> str:
        return LLMClassificationResult.__name__

    async def _prepare_step(self):
        logger.info(
            "Preparing embedding classification step for execution: %s",
            self.execution_id,
        )
        if self.llm_embedding_result is None:
            raise ValueError("LLMEmbeddingResult not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        self.llm_embedding_result = self._get_safe_workflow_context_key(
            LLMEmbeddingResult, context
        )
        self.ocr_result = self._get_not_mandatory_workflow_context_key(
            OcrResult, context
        )

    def _resolve_page_number(self, index: int) -> int:
        if self.ocr_result is not None and index < len(self.ocr_result.pages):
            return self.ocr_result.pages[index].page_number
        return index + 1

    def _resolve_supported_document_type(
        self, document_type_code: str
    ) -> SupportedDocumentType:
        try:
            return SupportedDocumentType.from_str(document_type_code)
        except Exception:
            return SupportedDocumentType.AUTRE

    async def _execute_internal(
        self,
    ) -> tuple[LLMClassificationResult, StepMetadata]:
        assert self.llm_embedding_result is not None

        if (
            self.extraction_parameters is not None
            and self.extraction_parameters.document_type is not None
        ):
            logger.info(
                "Embedding classification step skipped due to specified extraction parameters document type %s",
                self.extraction_parameters.document_type,
            )
            return (
                LLMClassificationResult(
                    data=DocumentClassification(
                        document_type=self.extraction_parameters.document_type,
                        explanation="Classification skipped due to specified extraction parameters document type.",
                        confidence=1.0,
                    )
                ),
                StepMetadata(step_name=self.__class__.__name__, execution_time=0),
            )

        allowed_document_types = None
        if (
            self.classification_parameters
            and self.classification_parameters.document_types
        ):
            allowed_document_types = [
                doc_type.value
                for doc_type in self.classification_parameters.document_types
            ]

        all_matches: list[tuple[str, float]] = []
        ocr_type = (
            self.ocr_result.ocr_type if self.ocr_result else None
        ) or OCRType.TESSERACT

        for index, embedding in enumerate(self.llm_embedding_result.embeddings_by_page):
            if not embedding:
                continue
            page_number = self._resolve_page_number(index)
            matches = await self.embedding_repository.find_top_similar(
                query_vector=embedding,
                limit=self.top_k,
                ocr_type=ocr_type.value,
                page_number=page_number,
                allowed_document_types=allowed_document_types,
            )
            for dto, similarity in matches:
                all_matches.append((dto.document_type_code, similarity))

        if not all_matches:
            return (
                LLMClassificationResult(
                    data=DocumentClassification(
                        document_type=SupportedDocumentType.AUTRE,
                        explanation="No embedding matches found.",
                        confidence=0.0,
                    )
                ),
                StepMetadata(step_name=self.__class__.__name__, execution_time=0),
            )

        all_matches.sort(key=lambda item: item[1], reverse=True)
        top_matches = all_matches[: self.top_k]
        filtered_matches = [
            match for match in top_matches if match[1] >= self.min_similarity
        ]

        if not filtered_matches:
            return (
                LLMClassificationResult(
                    data=DocumentClassification(
                        document_type=SupportedDocumentType.AUTRE,
                        explanation=(
                            "Embedding classification rejected: no match above "
                            f"{self.min_similarity:.2f} in top results."
                        ),
                        confidence=0.0,
                    )
                ),
                StepMetadata(step_name=self.__class__.__name__, execution_time=0),
            )

        vote_counts: dict[str, int] = {}
        for doc_type, _ in filtered_matches:
            vote_counts[doc_type] = vote_counts.get(doc_type, 0) + 1

        max_votes = max(vote_counts.values())
        winning_types = [
            doc_type for doc_type, count in vote_counts.items() if count == max_votes
        ]

        avg_similarity = sum(sim for _, sim in filtered_matches) / len(filtered_matches)

        if len(winning_types) == 1 and max_votes > len(filtered_matches) / 2:
            document_type_code = winning_types[0]
            supported_type = self._resolve_supported_document_type(document_type_code)
            return (
                LLMClassificationResult(
                    data=DocumentClassification(
                        document_type=supported_type,
                        explanation=(
                            "Embedding classification accepted by majority vote: "
                            f"{max_votes}/{len(filtered_matches)} above threshold."
                        ),
                        confidence=avg_similarity,
                    )
                ),
                StepMetadata(step_name=self.__class__.__name__, execution_time=0),
            )

        return (
            LLMClassificationResult(
                data=DocumentClassification(
                    document_type=SupportedDocumentType.AUTRE,
                    explanation=(
                        "Embedding classification rejected: no majority consensus "
                        "after filtering by similarity threshold."
                    ),
                    confidence=avg_similarity,
                )
            ),
            StepMetadata(step_name=self.__class__.__name__, execution_time=0),
        )
