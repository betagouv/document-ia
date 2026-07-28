from pathlib import Path

from document_ia_worker.core.prompt.prompt_configuration import (
    GENERIC_CLASSIFICATION_MODEL,
    SupportedDocumentType,
)
from document_ia_worker.core.prompt.prompt_service import PromptService
from document_ia_worker.exception.unsupported_document_type import (
    UnsupportedDocumentType,
)


def main() -> None:
    snapshots_dir = Path(__file__).resolve().parent.parent / "snapshots" / "prompts"
    extraction_output_dir = snapshots_dir / "extraction"
    classification_output_dir = snapshots_dir / "classification"
    extraction_output_dir.mkdir(parents=True, exist_ok=True)
    classification_output_dir.mkdir(parents=True, exist_ok=True)

    prompt_service = PromptService()

    classification_prompt = prompt_service.get_classification_prompt(
        GENERIC_CLASSIFICATION_MODEL
    )
    classification_output_path = classification_output_dir / "generic.txt"
    classification_output_path.write_text(classification_prompt, encoding="utf-8")
    print(f"Updated: {classification_output_path}")

    for document_type in SupportedDocumentType:
        try:
            prompt_text, _ = prompt_service.get_extraction_prompt(document_type)
        except UnsupportedDocumentType:
            continue

        output_path = extraction_output_dir / f"{document_type.value}.txt"
        output_path.write_text(prompt_text, encoding="utf-8")
        print(f"Updated: {output_path}")


if __name__ == "__main__":
    main()
