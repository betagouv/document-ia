import logging
from typing import Any, Dict, cast, TypeVar

import tiktoken
from openai import AsyncOpenAI, AuthenticationError, PermissionDeniedError
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from document_ia_infra.data.document.schema.document_extraction import (
    DocumentExtraction,
)
from document_ia_infra.exception.openai_authentification_error import (
    OpenAIAuthentificationError,
)
from document_ia_infra.openai.openai_settings import openai_settings
from document_ia_infra.openai.response_format import get_response_format
from document_ia_schemas import SupportedDocumentType

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class OpenAIManager:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=openai_settings.OPENAI_BASE_URL,
            api_key=openai_settings.OPENAI_API_KEY.get_secret_value()
            if openai_settings.OPENAI_API_KEY is not None
            else None,
            timeout=openai_settings.OPENAI_TIMEOUT,
            max_retries=openai_settings.OPENAI_MAX_RETRIES,
        )
        self.encoding = tiktoken.encoding_for_model(
            openai_settings.OPENAI_ENCODING_MODEL
        )

    async def get_classification_response(
        self,
        system_prompt: str,
        user_prompt: str,
        response_class: type[T],
        model: str,
    ) -> tuple[T, int, int]:
        return await self._generate_typed_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_class=response_class,
            model=model,
            temperature=0,
        )

    async def get_extraction_response(
        self,
        system_prompt: str,
        user_prompt: str,
        response_class: type[DocumentExtraction[T]],
        document_type: SupportedDocumentType,
        model: str,
    ) -> tuple[T, int, int]:
        inner_class = cast(Any, response_class.model_fields["properties"].annotation)

        (
            response,
            request_tokens,
            response_tokens,
        ) = await self._generate_typed_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_class=inner_class,
            model=model,
            temperature=0,
        )

        return (
            DocumentExtraction(  # pyright: ignore [reportReturnType]
                type=document_type,
                properties=response,
            ),
            request_tokens,
            response_tokens,
        )

    async def _generate_typed_response(
        self,
        system_prompt: str,
        user_prompt: str,
        response_class: type[T],
        model: str,
        temperature: float = 0,
    ) -> tuple[T, int, int]:
        request_tokens = len(self.encoding.encode(system_prompt)) + len(
            self.encoding.encode(user_prompt)
        )
        logger.info(f"Request size : {request_tokens}")

        message = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        data: Dict[str, Any] = {
            "model": model,
            "messages": message,
            "temperature": temperature,
            "extra_body": {
                "guided_json": get_response_format(response_class).model_json_schema()
            },
        }

        try:
            response: ChatCompletion = cast(
                ChatCompletion,
                await self.client.chat.completions.parse(
                    **data, response_format=get_response_format(response_class)
                ),
            )
            result = response.choices[0].message.content
            if result is None:
                raise Exception(f"Failed to generate response: {response}")

            response_tokens = len(self.encoding.encode(result))
            logger.info(f"Response size : {response_tokens}")

            return (
                response_class.model_validate_json(
                    result, by_alias=False, by_name=True
                ),
                request_tokens,
                response_tokens,
            )

        except AuthenticationError:
            raise OpenAIAuthentificationError()
        except Exception as e:
            # Apparently openai-python PermissionDeniedError cannot be caught specifically in an except (it throw a type error because it is not a BaseException subclass ?)
            if isinstance(e, PermissionDeniedError):
                raise OpenAIAuthentificationError()
            logger.error(f"Error generating response: {e}")
            raise e
