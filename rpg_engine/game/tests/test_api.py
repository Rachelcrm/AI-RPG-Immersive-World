from unittest.mock import patch

import pytest

from game.models import Book, Character, StorySession, World

pytestmark = pytest.mark.django_db


def test_health_reports_degraded_without_external_keys(api):
    resp = api.get('/api/health/')
    assert resp.status_code == 200
    assert resp.json()['database']['ok'] is True
    assert resp.json()['status'] in {'ok', 'degraded'}


def test_book_upload(api):
    resp = api.post('/api/books/upload/', {'title': 'demo', 'content': 'text'}, format='json')
    assert resp.status_code == 201
    assert Book.objects.filter(id=resp.json()['book']['id']).exists()


def test_world_generate_uses_openai_output(api, book):
    fake = {
        'world_name': 'Ashen Realm',
        'lore_summary': 'ash',
        'factions': ['A'],
        'locations': ['B'],
        'main_conflict': 'C',
    }
    with patch('game.views.OpenAIService.generate_world', return_value=fake):
        resp = api.post('/api/worlds/generate/', {'book_id': book.id}, format='json')
    assert resp.status_code == 201
    world = World.objects.get(id=resp.json()['world']['id'])
    assert world.name == 'Ashen Realm'
    assert world.book_id == book.id


def test_world_generate_returns_502_when_openai_fails(api, book):
    with patch('game.views.OpenAIService.generate_world', side_effect=ValueError('no key')):
        resp = api.post('/api/worlds/generate/', {'book_id': book.id}, format='json')
    assert resp.status_code == 502


def test_character_create_defaults(api, world):
    resp = api.post('/api/characters/create/', {'world': world.id, 'name': 'Kai', 'role': 'Ranger'}, format='json')
    assert resp.status_code == 201
    character = Character.objects.get(id=resp.json()['character']['id'])
    assert character.coins == 100
    assert character.level == 1


def test_session_start_rejects_character_from_other_world(api, world, character, book):
    other_world = World.objects.create(book=book, name='Other')
    resp = api.post(
        '/api/sessions/start/', {'world_id': other_world.id, 'character_id': character.id}, format='json'
    )
    assert resp.status_code == 400


def test_session_interact_advances_version(api, session):
    ai_output = {'narrative': 'You step into the hall.', 'events': [{'type': 'move', 'to': 'Ruin Hall'}]}
    with patch('game.services.story_service.OpenAIService.generate_story_turn', return_value=ai_output), patch(
        'game.services.story_service.MongoService.insert_conversation_log', return_value={'ok': True, 'id': 'x'}
    ), patch('game.services.story_service.MongoService.get_conversation_history', return_value=[]):
        resp = api.post(
            f'/api/sessions/{session.id}/interact/',
            {'user_input': 'I enter the ruin hall.', 'expected_version': 1},
            format='json',
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body['ai_output'] == 'You step into the hall.'
    assert body['session_version'] == 2
    assert body['events'] == [{'type': 'move', 'to': 'Ruin Hall'}]
    assert body['state']['location'] == 'Ruin Hall'
    assert body['notes'] == ['Kai moves to Ruin Hall.']
    session.refresh_from_db()
    assert session.is_processing is False
    assert session.last_turn_at is not None


def test_session_interact_stale_version_returns_409(api, session):
    resp = api.post(
        f'/api/sessions/{session.id}/interact/', {'user_input': 'look', 'expected_version': 5}, format='json'
    )
    assert resp.status_code == 409
    assert resp.json()['current_version'] == 1


def test_session_interact_releases_lock_on_ai_failure(api, session):
    with patch('game.services.story_service.OpenAIService.generate_story_turn', side_effect=ValueError('boom')), patch(
        'game.services.story_service.MongoService.get_conversation_history', return_value=[]
    ):
        resp = api.post(f'/api/sessions/{session.id}/interact/', {'user_input': 'look'}, format='json')
    assert resp.status_code == 502
    session.refresh_from_db()
    assert session.is_processing is False
    assert session.version == 1


def test_session_interact_while_processing_returns_409(api, session):
    StorySession.objects.filter(id=session.id).update(is_processing=True)
    resp = api.post(f'/api/sessions/{session.id}/interact/', {'user_input': 'look'}, format='json')
    assert resp.status_code == 409


def test_trade_quote_endpoint(api, character):
    resp = api.post(
        '/api/trades/quote/',
        {'character_id': character.id, 'item_name': 'Moon Shard', 'quantity': 2, 'base_price': '12.50', 'strategy': 'negotiation'},
        format='json',
    )
    assert resp.status_code == 200
    assert resp.json()['unit_price'] == '12.00'
    assert resp.json()['total_price'] == '25.20'


def test_trade_execute_endpoint(api, session, character):
    resp = api.post(
        '/api/trades/execute/',
        {
            'session_id': session.id,
            'character_id': character.id,
            'item_name': 'Moon Shard',
            'quantity': 1,
            'base_price': '10.00',
            'strategy': 'fixed',
        },
        format='json',
    )
    assert resp.status_code == 201
    assert resp.json()['buyer_coins'] == 89
    assert resp.json()['inventory'][0]['item_name'] == 'Moon Shard'


def test_ai_trade_falls_back_to_rule_parser(api, session, merchant, market_item):
    with patch('game.views.OpenAIService.parse_trade_intent', side_effect=ValueError('no key')):
        resp = api.post(
            '/api/trades/ai-act/',
            {'session_id': session.id, 'merchant_id': merchant.id, 'user_input': 'buy 2 traveler ration with negotiation'},
            format='json',
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body['intent_source'] == 'rule_fallback'
    assert body['intent'] == {'action': 'buy', 'item_name': 'Traveler Ration', 'quantity': 2, 'strategy': 'negotiation'}
    assert body['order']['side'] == 'buy'
    assert body['merchant_inventory'][0]['stock'] == 3
