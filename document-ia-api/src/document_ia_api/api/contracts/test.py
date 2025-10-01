from pydantic import BaseModel

from document_ia_infra.core.model.types.secret import SecretPayloadStr


class TestRequest(BaseModel):
    id: str
    description: SecretPayloadStr


class TestResponse(BaseModel):
    status: str
    test_param: str
    test_id: str
    secret_param: SecretPayloadStr
    payload: TestRequest
