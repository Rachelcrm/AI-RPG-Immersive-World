import io
from unittest.mock import patch

import pytest
from django.core.management import call_command

from game.models import StorySession
from game.services.offline_narrator import OfflineNarrator
from game.services.story_service import StoryService
from game.services.trade_service import TradeService, rule_based_trade_intent

pytestmark = pytest.mark.django_db


# --- session end ----------------------------------------------------------


def test_lethal_damage_ends_session(session, character):
    ai = OfflineNarrator()
    with patch.object(ai, 'generate_story_turn', return_value={'narrative': 'Ouch.', 'events': [{'type': 'damage', 'amount': 60}] * 2}), patch(
        'game.services.story_service.MongoService.insert_conversation_log', return_value={'ok': False}
    ), patch('game.services.story_service.MongoService.get_conversation_history', return_value=[]):
        result = StoryService(ai=ai).play_turn(session=session, user_input='charge')
    session.refresh_from_db()
    assert result.session_status == StorySession.STATUS_ENDED
    assert session.status == StorySession.STATUS_ENDED
    assert result.notes[-1] == 'The story ends here.'


def test_interact_refuses_ended_session(api, session):
    session.status = StorySession.STATUS_ENDED
    session.save()
    resp = api.post(f'/api/sessions/{session.id}/interact/', {'user_input': 'look'}, format='json')
    assert resp.status_code == 400


# --- state endpoint -------------------------------------------------------


def test_session_state_endpoint(api, session, character):
    character.current_location = 'Ruin Hall'
    character.save()
    with patch('game.views.MongoService.get_conversation_history', return_value=[{'user_input': 'a', 'ai_output': 'b'}]):
        resp = api.get(f'/api/sessions/{session.id}/')
    assert resp.status_code == 200
    body = resp.json()
    assert body['session']['id'] == session.id
    assert body['state']['location'] == 'Ruin Hall'
    assert body['history'] == [{'user_input': 'a', 'ai_output': 'b'}]
    assert api.get('/api/sessions/999/').status_code == 404


# --- trade intent parsing --------------------------------------------------


def test_rule_based_trade_intent():
    items = ['Moon Shard', 'Traveler Ration']
    assert rule_based_trade_intent('sell 3 moon shard, bargain hard', items) == {
        'action': 'sell',
        'item_name': 'Moon Shard',
        'quantity': 3,
        'strategy': 'negotiation',
    }
    assert rule_based_trade_intent('以物易物 交换', items)['strategy'] == 'barter'
    assert rule_based_trade_intent('buy something', items)['item_name'] == 'Moon Shard'  # first item default


def test_parse_intent_prefers_ai_then_falls_back():
    class GoodAI:
        def parse_trade_intent(self, **_):
            return {'action': 'buy', 'item_name': 'X', 'quantity': 1, 'strategy': 'fixed'}

    intent, source = TradeService.parse_intent(user_input='buy x', allowed_items=['X'], ai=GoodAI())
    assert source == 'ai' and intent['item_name'] == 'X'

    intent, source = TradeService.parse_intent(user_input='sell 2 x', allowed_items=['X'], ai=OfflineNarrator())
    assert source == 'rule_fallback' and intent == {'action': 'sell', 'item_name': 'X', 'quantity': 2, 'strategy': 'fixed'}


# --- offline narrator ------------------------------------------------------


def test_offline_narrator_grammar():
    n = OfflineNarrator(seed=1)
    state = {'known_locations': ['Ash Market'], 'nearby_npcs': [{'name': 'Pell', 'role': 'Trader'}], 'quests': []}
    assert n.generate_story_turn(user_input='go to ash market', state=state)['events'] == [{'type': 'move', 'to': 'Ash Market'}]
    assert n.generate_story_turn(user_input='go to nowhere', state=state)['events'] == []
    assert n.generate_story_turn(user_input='rest', state=state)['events'] == [{'type': 'heal', 'amount': 20}]
    talk = n.generate_story_turn(user_input='talk', state=state)['events']
    assert talk[0]['type'] == 'quest_start' and talk[0]['title'] == "Pell's errand"
    assert n.generate_story_turn(user_input='dance', state=state)['events'] == []


def test_offline_world_uses_capitalized_phrases():
    spec = OfflineNarrator().generate_world(book_title='t', book_content='He walked to Ash Market and the Ruin Hall.')
    assert spec['locations'] == ['Ash Market', 'Ruin Hall']


# --- play command ----------------------------------------------------------


def test_play_command_runs_scripted_session(tmp_path):
    book = tmp_path / 'demo.txt'
    book.write_text('The Ember Guard held the Ruin Hall. Beyond lay the Ash Market.')
    script = iter(['look around', '/inventory', 'go to Ash Market', '/market', '/buy 1 torch', '/status', '/quit'])
    out = io.StringIO()
    with patch('builtins.input', lambda _='': next(script)), patch(
        'game.services.story_service.MongoService.insert_conversation_log', return_value={'ok': False}
    ), patch('game.services.story_service.MongoService.get_conversation_history', return_value=[]):
        call_command('play', book=str(book), offline=True, name='Kai', role='Ranger', stdout=out)
    text = out.getvalue()
    assert 'World of demo' in text
    assert 'Market: 3 items' in text
    assert 'Kai moves to Ash Market.' in text
    assert 'you bought Torch x1' in text
    assert 'Farewell.' in text
    session = StorySession.objects.get()
    assert session.character.current_location == 'Ash Market'
    assert session.character.inventory_items.filter(item_name='Torch').exists()


def test_play_command_resumes_session_and_handles_eof(session):
    out = io.StringIO()
    with patch('builtins.input', side_effect=EOFError):
        call_command('play', session=session.id, offline=True, stdout=out)
    assert 'Demo Adventure' in out.getvalue()
    assert 'Farewell.' in out.getvalue()


def test_play_command_requires_a_source():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command('play', offline=True)
