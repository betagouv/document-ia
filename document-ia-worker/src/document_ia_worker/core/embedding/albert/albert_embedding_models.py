from pydantic import BaseModel, ConfigDict


class AlbertEmbeddingRequest(BaseModel):
    input: list[int] | list[list[int]] | str | list[str]
    model: str = "openweight-embeddings"
    dimensions: int | None = None
    encoding_format: str | None = None

    model_config = ConfigDict(extra="allow")


class AlbertEmbeddingData(BaseModel):
    embedding: list[float]
    index: int
    object: str = "embedding"

    model_config = ConfigDict(extra="allow")


class AlbertEmbeddingUsageImpacts(BaseModel):
    kWh: float | int | None = None
    kgCO2eq: float | int | None = None

    model_config = ConfigDict(extra="allow")


class AlbertEmbeddingUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | int | None = None
    impacts: AlbertEmbeddingUsageImpacts | None = None
    requests: int | None = None

    model_config = ConfigDict(extra="allow")


class AlbertEmbeddingResponse(BaseModel):
    data: list[AlbertEmbeddingData]
    model: str
    object: str
    usage: AlbertEmbeddingUsage | None = None
    id: str | None = None

    model_config = ConfigDict(extra="allow")
