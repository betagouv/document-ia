import logging
import math
import threading
from pathlib import Path
from typing import Optional, Any, Iterable, Protocol, runtime_checkable, cast

from pymupdf import pymupdf, Document
from PIL import Image

from document_ia_infra.data.workflow.dto.workflow_v2_dto import PreprocessFileParams

from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepMetadata,
)
from document_ia_worker.workflow.step.base_file_manipulation_step import (
    BaseFileManipulationStep,
)
from document_ia_worker.workflow.step.step_result.download_file_result import (
    DownloadFileResult,
)
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)
from document_ia_worker.core.preprocessing.yoloworld_crop import yoloworld_crop_image

logger = logging.getLogger(__name__)


@runtime_checkable
class RectLike(Protocol):
    width: float
    height: float


@runtime_checkable
class PixmapLike(Protocol):
    width: int
    height: int

    def save(self, filename: str) -> None: ...


@runtime_checkable
class PageLike(Protocol):
    rect: RectLike
    number: int

    def get_pixmap(self, **kwargs: Any) -> PixmapLike: ...


_PDF_LOCK = threading.Lock()


class PreprocessFileStep(BaseFileManipulationStep[PreprocessFileResult]):
    download_file_result: Optional[DownloadFileResult] = None

    def __init__(
        self,
        main_workflow_context: MainWorkflowContext,
        params: Optional[PreprocessFileParams] = None,
    ):
        super().__init__(main_workflow_context, subfolder="preprocess")
        self.params = params or PreprocessFileParams()
        self.targeted_dpi = 180
        self.max_long_edge = 1800
        self.max_pixel_size = 2_000_000
        self.min_long_edge = 1500
        self.force_grayscale = True

    def get_context_result_key(self) -> str:
        return PreprocessFileResult.__name__

    def inject_workflow_context(self, context: dict[str, Any]):
        not_typed_data = context.get(DownloadFileResult.__name__)
        if not_typed_data is None or not isinstance(not_typed_data, DownloadFileResult):
            raise ValueError("DownloadFileReturnData not found in context")
        self.download_file_result = not_typed_data

    async def _prepare_step(self):
        if self.download_file_result is None:
            raise ValueError("DownloadFileReturnData not injected in context")
        # Ensure output directory exists
        Path(self.tmp_folder_path).mkdir(parents=True, exist_ok=True)

    async def _execute_internal(
        self,
    ) -> tuple[PreprocessFileResult, Optional[StepMetadata]]:
        if self.download_file_result is None:
            raise ValueError("DownloadFileReturnData not injected in context")

        if self.download_file_result.content_type == "application/pdf":
            logger.info("File is a PDF, preprocessing accordingly.")
            result = self._preprocess_pdf()
        else:
            logger.info("File is a Picture, no preprocessing needed.")
            result = PreprocessFileResult(
                output_files_path=[self.download_file_result.file_path]
            )

        if self.params.yoloworld.enabled:
            result = self._apply_yoloworld(result)

        return result, None

    def _apply_yoloworld(
        self, preprocess_result: PreprocessFileResult
    ) -> PreprocessFileResult:
        yolo_params = self.params.yoloworld
        output_paths: list[str] = []
        out_dir = Path(self.tmp_folder_path)
        out_dir.mkdir(parents=True, exist_ok=True)

        for index, file_path in enumerate(preprocess_result.output_files_path, start=1):
            source_path = Path(file_path)
            output_path = out_dir / f"{source_path.stem}_{index}_yoloworld_crop.png"
            with Image.open(source_path) as image:
                cropped_image = yoloworld_crop_image(
                    image,
                    class_name=yolo_params.class_name,
                    margin=yolo_params.margin,
                    confidence_threshold=yolo_params.confidence_threshold,
                    image_size=yolo_params.image_size,
                )
                cropped_image.save(output_path, format="PNG")
                cropped_image.close()
            output_paths.append(str(output_path))

        return PreprocessFileResult(output_files_path=output_paths)

    def _preprocess_pdf(self) -> PreprocessFileResult:
        with _PDF_LOCK:
            image_paths: list[str] = []
            assert self.download_file_result
            doc: Document = pymupdf.open(filename=self.download_file_result.file_path)
            out_dir = Path(self.tmp_folder_path)
            out_dir.mkdir(parents=True, exist_ok=True)
            base_name = Path(self.download_file_result.file_path).stem
            try:
                pages = cast(Iterable[PageLike], doc)
                for page in pages:
                    page_width = page.rect.width
                    page_height = page.rect.height

                    # Zoom cible basé sur le DPI souhaité
                    # 72 DPI est la résolution "naturelle" des pdf
                    zoom = self.targeted_dpi / 72.0

                    # Taille prédite avec ce zoom
                    predicted_width = page_width * zoom
                    predicted_height = page_height * zoom

                    # On borne par la longueur max et le nombre total de pixels
                    scale_by_edge = self.max_long_edge / max(
                        predicted_width, predicted_height
                    )
                    scale_by_mp = math.sqrt(
                        self.max_pixel_size / (predicted_width * predicted_height)
                    )
                    clamp_factor = min(1.0, scale_by_edge, scale_by_mp)

                    # Si trop petit, on remonte au minimum requis
                    if (
                        clamp_factor == 1.0
                        and max(predicted_width, predicted_height) < self.min_long_edge
                    ):
                        clamp_factor = self.min_long_edge / max(
                            predicted_width, predicted_height
                        )

                    effective_zoom = zoom * clamp_factor
                    mat = pymupdf.Matrix(effective_zoom, effective_zoom)

                    # Préparation des kwargs pour get_pixmap (niveau de gris + pas d’alpha)
                    kwargs: dict[str, Any] = {"matrix": mat, "alpha": False}
                    if self.force_grayscale and hasattr(pymupdf, "csGRAY"):
                        kwargs["colorspace"] = pymupdf.csGRAY

                    pix = page.get_pixmap(**kwargs)
                    try:
                        logger.debug(
                            f"Page {page.number}: pts={int(predicted_width)}x{int(predicted_height)} -> "
                            f"px={pix.width}x{pix.height}  (eff_dpi≈{effective_zoom * 72.0:.1f})"
                        )

                        image_path = str(out_dir / f"{base_name}_{page.number}.png")
                        pix.save(image_path)
                        image_paths.append(image_path)
                    finally:
                        # Libère la référence du pixmap
                        del pix
            finally:
                doc.close()  # Ferme le document PDF

            # noinspection PyUnreachableCode
            return PreprocessFileResult(output_files_path=image_paths)
