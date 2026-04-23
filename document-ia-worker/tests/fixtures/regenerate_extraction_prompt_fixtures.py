from pathlib import Path

from document_ia_worker.core.prompt.prompt_configuration import SupportedDocumentType
from document_ia_worker.core.prompt.prompt_service import PromptService
from document_ia_worker.exception.unsupported_document_type import (
    UnsupportedDocumentType,
)


def main() -> None:
    output_dir = Path(__file__).resolve().parent / "prompts" / "extraction"
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt_service = PromptService()

    for document_type in SupportedDocumentType:
        try:
            prompt_text, _ = prompt_service.get_extraction_prompt(document_type)
        except UnsupportedDocumentType:
            continue

        output_path = output_dir / f"{document_type.value}.txt"
        output_path.write_text(prompt_text, encoding="utf-8")
        print(f"Updated: {output_path}")


if __name__ == "__main__":
    main()
