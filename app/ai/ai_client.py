from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from config.settings import get_settings


class AIClient(Protocol):
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate a text response from an AI model."""


@dataclass(frozen=True)
class StaticAIClient:
    fallback_response: str = (
        "I could not find enough official FAQ information to answer this safely. "
        "I created a ticket for manual support."
    )

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return self.fallback_response


class OpenAIChatClient:
    def __init__(self, model: str = "gpt-4.1-mini") -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required to use OpenAIChatClient.")
        self.model = model
        self.api_key = settings.openai_api_key

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return str(response.output_text).strip()

