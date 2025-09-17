import logging
from typing import Any, Dict, cast, TypeVar

import tiktoken
from openai import AsyncOpenAI, AuthenticationError
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from document_ia_infra.openai.openai_settings import openai_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class OpenAIManager:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=openai_settings.ALBERT_BASE_URL,
            api_key=openai_settings.ALBERT_API_KEY,
        )
        self.encoding = tiktoken.encoding_for_model(openai_settings.ENCODING_MODEL)

    async def generate_typped_response(
        self,
        system_prompt: str,
        user_prompt: str,
        response_class: type[T],
        model: str = openai_settings.ALBERT_LARGE_MODEL,
        temperature: float = 0.7,
    ) -> T:
        tokens = self.encoding.encode(system_prompt) + self.encoding.encode(user_prompt)
        logger.info(f"Request size : {len(tokens)}")

        message = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        data: Dict[str, Any] = {
            "model": model,
            "messages": message,
            "stream": False,
            "temperature": temperature,
            "extra_body": {"guided_json": response_class.model_json_schema()},
        }

        try:
            response: ChatCompletion = cast(
                ChatCompletion, await self.client.chat.completions.create(**data)
            )
            result = response.choices[0].message.content
            if result is None:
                raise Exception(f"Failed to generate response: {response}")

            response_tokens = self.encoding.encode(result)
            logger.info(f"Reponse size : {len(response_tokens)}")

            return response_class.model_validate_json(result)

        except AuthenticationError as e:
            logger.error(f"OpenAI authentication error: {e}")
            raise Exception(
                "Retryable OpenAI API key is invalid or not configured properly"
            )
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            raise e


openai_manager = OpenAIManager()
