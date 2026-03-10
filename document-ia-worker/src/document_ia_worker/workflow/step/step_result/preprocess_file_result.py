from pydantic import BaseModel


class PreprocessFileResult(BaseModel):
    output_files_path: list[str]
