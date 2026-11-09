from django.conf import settings

from game.services.llm_service import LLMService


class OpenAIService(LLMService):
    """OpenAI Responses API provider. Prompts and parsing live in LLMService."""

    provider = 'openai'
    key_setting = 'OPENAI_API_KEY'

    def __init__(self) -> None:
        self._client = None
        if settings.OPENAI_API_KEY:
            from openai import OpenAI  # imported lazily so the SDK is optional

            self._client = OpenAI(api_key=settings.OPENAI_API_KEY)

    @property
    def model(self) -> str:
        return settings.OPENAI_MODEL

    def is_configured(self) -> bool:
        return getattr(self, '_client', None) is not None

    def _complete(self, prompt: str, *, max_tokens: int) -> str:
        response = self._client.responses.create(model=self.model, input=prompt, max_output_tokens=max_tokens)
        return response.output_text or ''
