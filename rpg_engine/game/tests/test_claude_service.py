import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from game.services.claude_service import API_URL, ClaudeService
from game.services.llm_service import get_llm_service
from game.services.openai_service import OpenAIService


def _response(payload: dict):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__.return_value = resp
    return resp


def _message(text: str, stop_reason: str = 'end_turn') -> dict:
    return {
        'content': [{'type': 'text', 'text': text}],
        'stop_reason': stop_reason,
        'usage': {'input_tokens': 10, 'output_tokens': 5},
    }


def test_complete_sends_messages_request():
    svc = ClaudeService(api_key='k', model='claude-test')
    with patch('urllib.request.urlopen', return_value=_response(_message('OK'))) as urlopen:
        assert svc.check()['ok'] is True
    request = urlopen.call_args.args[0]
    body = json.loads(request.data)
    assert request.full_url == API_URL
    assert request.get_header('X-api-key') == 'k'
    assert request.get_header('Anthropic-version') == '2023-06-01'
    assert body['model'] == 'claude-test'
    assert body['messages'] == [{'role': 'user', 'content': 'Reply with exactly: OK'}]
    assert 'JSON' in body['system']
    assert svc.last_usage['output_tokens'] == 5


def test_story_turn_goes_through_shared_parser():
    text = '```json\n{"narrative": "The gate creaks.", "events": [{"type": "heal", "amount": 3}]}\n```'
    svc = ClaudeService(api_key='k')
    with patch('urllib.request.urlopen', return_value=_response(_message(text))):
        out = svc.generate_story_turn(
            world_name='W', world_lore_summary='L', character_name='C', character_role='R', user_input='open gate'
        )
    assert out == {'narrative': 'The gate creaks.', 'events': [{'type': 'heal', 'amount': 3}], 'objective': ''}


def test_unconfigured_raises_without_network():
    svc = ClaudeService(api_key='')
    with patch('urllib.request.urlopen') as urlopen:
        assert svc.check()['ok'] is False
        with pytest.raises(ValueError, match='ANTHROPIC_API_KEY'):
            svc.generate_world(book_title='t', book_content='c')
    urlopen.assert_not_called()


def test_http_error_surfaces_api_message():
    err = urllib.error.HTTPError(
        API_URL, 401, 'Unauthorized', {}, io.BytesIO(b'{"error": {"message": "invalid x-api-key"}}')
    )
    svc = ClaudeService(api_key='bad')
    with patch('urllib.request.urlopen', side_effect=err):
        with pytest.raises(RuntimeError, match='401: invalid x-api-key'):
            svc._complete('hi', max_tokens=5)


def test_retries_on_overloaded():
    overloaded = urllib.error.HTTPError(API_URL, 529, 'Overloaded', {}, io.BytesIO(b'{}'))
    svc = ClaudeService(api_key='k')
    with patch('urllib.request.urlopen', side_effect=[overloaded, _response(_message('fine'))]), patch(
        'game.services.claude_service.time.sleep'
    ):
        assert svc._complete('hi', max_tokens=5) == 'fine'


def test_provider_selection(settings):
    settings.LLM_PROVIDER = ''
    settings.ANTHROPIC_API_KEY = 'k'
    assert isinstance(get_llm_service(), ClaudeService)
    settings.ANTHROPIC_API_KEY = ''
    settings.OPENAI_API_KEY = ''
    assert isinstance(get_llm_service(), OpenAIService)
    settings.LLM_PROVIDER = 'claude'
    assert isinstance(get_llm_service(), ClaudeService)
    settings.LLM_PROVIDER = 'nope'
    with pytest.raises(ValueError):
        get_llm_service()


def test_truncated_reply_is_retried_with_bigger_budget():
    svc = ClaudeService(api_key='k')
    replies = [_response(_message('{"narr', stop_reason='max_tokens')), _response(_message('{"narrative": "ok"}'))]
    with patch('urllib.request.urlopen', side_effect=replies) as urlopen:
        assert svc._complete('hi', max_tokens=100) == '{"narrative": "ok"}'
    assert json.loads(urlopen.call_args_list[1].args[0].data)['max_tokens'] == 200
