from document_ia_worker.core.ocr.ocr_result import HttpOcrResult
from document_ia_worker.workflow.step.extract_content_ocr.extract_content_http_ocr import (
    ExtractContentHttpOcrStep,
)
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)


class FakeHttpOcrService:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def extract_text_from_image(self, file_path: str, mime_type: str):
        self.calls.append((file_path, mime_type))
        return HttpOcrResult(success=True, content=f"text:{file_path}")


async def test_http_ocr_prefers_preprocess_file_result(main_workflow_context):
    service = FakeHttpOcrService()
    step = ExtractContentHttpOcrStep(main_workflow_context, service)
    step.inject_workflow_context(
        {
            PreprocessFileResult.__name__: PreprocessFileResult(
                output_files_path=["/tmp/page_1.png", "/tmp/page_2.png"]
            ),
        }
    )

    result, _ = await step.execute()

    assert service.calls == [
        ("/tmp/page_1.png", "image/png"),
        ("/tmp/page_2.png", "image/png"),
    ]
    assert [page.text for page in result.pages] == [
        "text:/tmp/page_1.png",
        "text:/tmp/page_2.png",
    ]
    assert [page.page_number for page in result.pages] == [1, 2]
    assert all(page.has_failed is False for page in result.pages)
