import json
import logging
from typing import Any, Dict, cast, TypeVar
from pathlib import Path
import datetime

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
        self.has_to_dump_requests = openai_settings.OPENAI_DUMP_REQUESTS
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
            request_type="classification",
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
            request_type="extraction",
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
        request_type: str = "classification",
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
        }

        if self.has_to_dump_requests:
            self.dump_request(
                response_class=response_class, data=data, request_type=request_type
            )

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

    def dump_request(
        self, response_class: type[T], data: Dict[str, Any], request_type: str
    ) -> None:
        json_schema = get_response_format(response_class).model_json_schema()

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_response",  # Nom arbitraire requis par l'API
                "strict": True,  # Souvent True par défaut avec .parse()
                "schema": json_schema,
            },
        }

        payload = {
            "model": data["model"],
            "messages": data["messages"],
            "temperature": data["temperature"],
            "response_format": response_format,
        }

        # Resolve project root: walk up from CWD to find a folder containing pyproject.toml.
        def _resolve_project_root(start: Path) -> Path:
            for parent in [start, *start.parents]:
                if (parent / "pyproject.toml").exists():
                    return parent
            return start  # fallback to start

        cwd = Path.cwd()
        project_root = _resolve_project_root(cwd)

        # Hierarchical folder: openai-dumps/YYYY/MM/DD/<type>/<N>/ at project root
        now = datetime.datetime.now(datetime.UTC)
        year = f"{now.year:04d}"
        month = f"{now.month:02d}"
        day = f"{now.day:02d}"
        base_dir = project_root / "openai-dumps" / year / month / day / request_type
        base_dir.mkdir(parents=True, exist_ok=True)

        # Find next incremental request number N
        existing = [p for p in base_dir.iterdir() if p.is_dir() and p.name.isdigit()]
        next_n = 1
        if existing:
            try:
                next_n = max(int(p.name) for p in existing) + 1
            except ValueError:
                next_n = 1
        dump_dir = base_dir / str(next_n)
        dump_dir.mkdir(parents=True, exist_ok=True)

        if openai_settings.OPENAI_API_KEY is None:
            raise ValueError("OPENAI_API_KEY is not set in openai_settings")

        data_path = dump_dir / "data.json"
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        curl_command = (
            f'curl -X POST "{openai_settings.OPENAI_BASE_URL}/chat/completions" '
            f'-H "Content-Type: application/json" '
            f'-H "Authorization: Bearer {openai_settings.OPENAI_API_KEY.get_secret_value()}" '
            f"-d @{data_path}"
        )
        curl_path = dump_dir / "curl.sh"
        with open(curl_path, "w", encoding="utf-8") as f:
            f.write(curl_command + "\n")

        logger.info(f"OpenAI request dumped to {dump_dir}")
