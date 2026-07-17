import asyncio
import base64
import logging
import time
from typing import Any, Coroutine, Optional

import httpx
import cv2
import numpy as np

from document_ia_infra.openai.openai_settings import openai_settings
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepMetadata,
)
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.ocr_result import (
    OcrResult,
    OcrResultPage,
)
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)
from document_ia_worker.workflow.step.step_result.barcode_result import BarcodeResult
from document_ia_infra.data.event.schema.barcode import BarcodeVariant

logger = logging.getLogger(__name__)


class ExtractContentOcrLightOnStep(BaseStep[OcrResult]):
    preprocess_file_result: Optional[PreprocessFileResult] = None
    barcode_result: Optional[BarcodeResult] = None

    def __init__(self, main_workflow_context: MainWorkflowContext):
        self.execution_id = main_workflow_context.execution_id

    def get_context_result_key(self) -> str:
        return OcrResult.__name__

    async def _prepare_step(self):
        logger.info(
            f"Preparing LightOn ocr extraction step for file: {self.execution_id}"
        )
        if self.preprocess_file_result is None:
            raise ValueError("PreprocessFileReturnData not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        not_typed_data = context.get(PreprocessFileResult.__name__)
        if not_typed_data is None or not isinstance(
            not_typed_data, PreprocessFileResult
        ):
            raise ValueError("PreprocessFileReturnData not found in context")
        self.preprocess_file_result = not_typed_data

        barcode_data = context.get(BarcodeResult.__name__)
        if barcode_data is not None and isinstance(barcode_data, BarcodeResult):
            self.barcode_result = barcode_data

    async def _execute_internal(self) -> tuple[OcrResult, Optional[StepMetadata]]:
        assert self.preprocess_file_result is not None

        api_key = (
            openai_settings.OPENAI_API_KEY.get_secret_value()
            if openai_settings.OPENAI_API_KEY
            else None
        )
        base_url = openai_settings.OPENAI_BASE_URL

        if not api_key or not base_url:
            raise ValueError("OPENAI_API_KEY and OPENAI_BASE_URL must be configured")

        timeout = httpx.Timeout(60.0, connect=60.0)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        semaphore = asyncio.Semaphore(openai_settings.LIGHT_ON_OCR_PARALLEL_CALLS)

        async with httpx.AsyncClient(timeout=timeout) as client:
            tasks: list[Coroutine[Any, Any, OcrResultPage]] = []
            for idx, file_path in enumerate(
                self.preprocess_file_result.output_files_path
            ):
                page_number = idx + 1
                tasks.append(
                    self._process_image(
                        client, base_url, headers, file_path, page_number, semaphore
                    )
                )

            pages_results: list[OcrResultPage] = list(await asyncio.gather(*tasks))

        return OcrResult(pages=pages_results), None

    async def _process_image(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        headers: dict[str, str],
        file_path: str,
        page_number: int,
        semaphore: asyncio.Semaphore,
    ) -> OcrResultPage:
        async with semaphore:
            logger.info(f"Processing image {file_path} with LightOn API")
            try:
                barcodes = self._get_barcodes_for_page(page_number)

                if barcodes:
                    b64_content = self._mask_barcodes(file_path, page_number, barcodes)
                else:
                    b64_content = self._read_image_as_b64(file_path)

                payload = self._prepare_payload(file_path, b64_content)
                extracted_text = await self._make_http_call(
                    client, base_url, headers, payload, page_number
                )

                return OcrResultPage(
                    text=extracted_text,
                    page_number=page_number,
                    has_failed=False,
                )
            except Exception as e:
                logger.error(
                    f"Error during LightOn OCR processing for page {page_number}: {e}"
                )
                return OcrResultPage(
                    text=None,
                    page_number=page_number,
                    has_failed=True,
                )

    def _get_barcodes_for_page(self, page_number: int) -> list[BarcodeVariant]:
        if not self.barcode_result:
            return []
        for page in self.barcode_result.pages:
            if page.page_number == page_number:
                return page.barcodes
        return []

    def _mask_barcodes(
        self, file_path: str, page_number: int, barcodes: list[BarcodeVariant]
    ) -> str:
        """
        Masque les éléments visuellement complexes (2D-Doc, QR Code, Code-barres)
        présents sur l'image en dessinant un polygone noir par-dessus.

        Pourquoi ?
        Les LLMs Vision (comme LightOn) essaient d'interpréter chaque pixel. Un 2D-Doc
        ou un QR Code agit comme du "bruit visuel" extrêmement dense, ce qui sature
        le modèle et allonge considérablement son temps de traitement (timeout).
        En masquant ces zones préalablement détectées par la step `extract_barcode_data`,
        on garantit une lecture rapide et fiable du reste du document.
        """
        logger.info(
            f"Found {len(barcodes)} barcodes on page {page_number}. Masking them."
        )
        img = cv2.imread(file_path)
        if img is None:
            raise ValueError(f"Failed to read image {file_path}")

        # On dessine un rectangle/polygone plein (noir) sur chaque code
        for barcode in barcodes:
            pos = barcode.position
            pts = np.array(
                [pos.top_left, pos.top_right, pos.bottom_right, pos.bottom_left],
                np.int32,
            )
            pts = pts.reshape((-1, 1, 2))
            cv2.fillPoly(img, [pts], (0, 0, 0))

        success, encoded_img = cv2.imencode(".png", img)  # pyright: ignore
        if not success:
            del img
            raise ValueError(
                f"Failed to encode image with masked barcodes for {file_path}"
            )

        b64_str = base64.b64encode(encoded_img.tobytes()).decode("ascii")  # pyright: ignore

        # Explicitly release OpenCV memory
        del img
        del encoded_img

        return b64_str

    def _read_image_as_b64(self, file_path: str) -> str:
        with open(file_path, "rb") as f:
            raw_bytes = f.read()
        return base64.b64encode(raw_bytes).decode("ascii")

    def _prepare_payload(self, file_path: str, b64_content: str) -> dict[str, Any]:
        # Since preprocess_file outputs images, assume png or derive it
        mime_type = "image/png" if file_path.endswith(".png") else "image/jpeg"
        data_url = f"data:{mime_type};base64,{b64_content}"

        return {
            "model": "openweight-ocr",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": data_url}}],
                }
            ],
            "temperature": 0,
        }

    async def _make_http_call(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        page_number: int,
    ) -> str:
        # Ensures URL is correctly formatted if base_url ends with / or not
        url = f"{base_url.rstrip('/')}/chat/completions"

        start_time = time.time()
        response = await client.post(url, headers=headers, json=payload)
        elapsed_time = time.time() - start_time
        logger.info(
            f"LightOn API request for page {page_number} took {elapsed_time:.2f} seconds"
        )

        response.raise_for_status()

        data = response.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
