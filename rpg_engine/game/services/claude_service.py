"""Anthropic Claude provider, talking to the Messages API over plain HTTPS.

Uses only the standard library (urllib), so no extra dependency is needed.
Prompts and output parsing are inherited from LLMService.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from django.conf import settings

from game.services.llm_service import LLMService

API_URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'
RETRYABLE = {429, 500, 502, 503, 504, 529}

SYSTEM_PROMPT = (
    'You are the engine behind a text RPG. Every request tells you what to return. '
    'When it asks for JSON, reply with that JSON value only: no prose before or after, no markdown fences.'
)


class ClaudeService(LLMService):
    provider = 'anthropic'
    key_setting = 'ANTHROPIC_API_KEY'

    def __init__(self, *, api_key: str | None = None, model: str | None = None, timeout: float = 90.0) -> None:
        self._api_key = api_key if api_key is not None else settings.ANTHROPIC_API_KEY
        self._model = model or settings.ANTHROPIC_MODEL
        self._timeout = timeout
        self.last_usage: dict = {}
        self.last_stop_reason: str = ''

    @property
    def model(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _complete(self, prompt: str, *, max_tokens: int) -> str:
        body = {
            'model': self._model,
            'max_tokens': max_tokens,
            'system': SYSTEM_PROMPT,
            'messages': [{'role': 'user', 'content': prompt}],
        }
        data = self._post(body)
        if data.get('stop_reason') == 'max_tokens':
            # A cut-off reply is usually half a JSON object; one retry with a bigger budget.
            body['max_tokens'] = max_tokens * 2
            data = self._post(body)
        self.last_usage = data.get('usage') or {}
        self.last_stop_reason = data.get('stop_reason') or ''
        return ''.join(block.get('text', '') for block in data.get('content', []) if block.get('type') == 'text')

    def _post(self, body: dict, *, attempts: int = 3) -> dict:
        payload = json.dumps(body).encode('utf-8')
        headers = {
            'x-api-key': self._api_key,
            'anthropic-version': API_VERSION,
            'content-type': 'application/json',
        }
        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(API_URL, data=payload, headers=headers, method='POST')
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    return json.loads(response.read().decode('utf-8'))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode('utf-8', errors='replace')
                if exc.code in RETRYABLE and attempt < attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f'Claude API error {exc.code}: {self._error_message(detail)}') from exc
            except urllib.error.URLError as exc:
                if attempt < attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f'Claude API unreachable: {exc.reason}') from exc
        raise RuntimeError('Claude API request failed.')

    @staticmethod
    def _error_message(detail: str) -> str:
        try:
            return json.loads(detail)['error']['message']
        except (ValueError, KeyError, TypeError):
            return detail[:300]
