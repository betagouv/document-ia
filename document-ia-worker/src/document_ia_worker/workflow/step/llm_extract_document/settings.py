from pydantic_settings import BaseSettings


class LLMExtractDocumentSettings(BaseSettings):
    OPENAI_REPLAY_PAYLOAD_SAVE_ENABLED: bool = False
    OPENAI_REPLAY_PAYLOAD_SAVE_PATH: str = "/tmp/document-ia-openai-replay"

settings = LLMExtractDocumentSettings()