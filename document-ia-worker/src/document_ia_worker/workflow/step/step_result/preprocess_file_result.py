from dataclasses import dataclass


@dataclass
class PreprocessFileResult:
    output_files_path: list[str]
