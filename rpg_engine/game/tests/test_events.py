from unittest.mock import patch

import pytest

from game.models import InventoryItem, Quest
from game.services.events import (
    CharacterObserver,
    EventRuleLayer,
    GameEvent,
    GameStateBus,
    InventoryObserver,
    QuestObserver,
    TurnContext,
)
from game.services.story_service import StoryService

pytestmark = pytest.mark.django_db


def _ctx(session, character):
    return TurnContext(session=session, character=character, user_input='x', narrative='y')


def _bus():
    return GameStateBus().subscribe(CharacterObserver()).subscribe(InventoryObserver()).subscribe(QuestObserver())


# --- rule layer -----------------------------------------------------------


def test_rule_layer_drops_unknown_and_malformed_events():
    events = EventRuleLayer.sanitize(
        [
            {'type': 'teleport', 'to': 'Moon'},
            'not a dict',
            {'type': 'damage'},  # missing amount
            {'type': 'move', 'to': ''},
            {'type': 'heal', 'amount': 'lots'},
        ]
    )
    assert events == []


def test_rule_layer_clamps_amounts_and_normalizes_type():
    events = EventRuleLayer.sanitize(
        [
            {'type': 'DAMAGE', 'amount': 9999, 'source': 'dragon'},
            {'type': 'gain_coins', 'amount': -5},
            {'type': 'gain_item', 'item_name': 'Rope', 'quantity': 50},
        ]
    )
    assert [e.to_dict() for e in events] == [
        {'type': 'damage', 'amount': 60, 'source': 'dragon'},
        {'type': 'gain_item', 'item_name': 'Rope', 'quantity': 10},
    ]


def test_rule_layer_handles_non_list():
    assert EventRuleLayer.sanitize(None) == []
    assert EventRuleLayer.sanitize({'type': 'damage'}) == []


# --- bus / observers ------------------------------------------------------


def test_bus_routes_only_to_observers_that_handle_type(session, character):
    class Spy:
        seen = []

        def handles(self):
            return {'move'}

        def on_event(self, event, ctx):
            self.seen.append(event.type)

    spy = Spy()
    bus = GameStateBus().subscribe(spy)
    applied = bus.publish([GameEvent('move', {'to': 'Hall'}), GameEvent('damage', {'amount': 1})], _ctx(session, character))
    assert spy.seen == ['move']
    assert [e.type for e in applied] == ['move', 'damage']


def test_character_observer_damage_heal_and_death(session, character):
    ctx = _ctx(session, character)
    _bus().publish([GameEvent('damage', {'amount': 30, 'source': 'trap'})], ctx)
    character.refresh_from_db()
    assert character.hp == 70

    _bus().publish([GameEvent('heal', {'amount': 999})], ctx)
    character.refresh_from_db()
    assert character.hp == 100  # capped at max_hp

    _bus().publish([GameEvent('damage', {'amount': 60}), GameEvent('damage', {'amount': 60})], ctx)
    character.refresh_from_db()
    assert character.hp == 0
    assert character.is_alive is False
    assert any('fallen' in n for n in ctx.notes)


def test_character_observer_move_coins_status_level(session, character):
    ctx = _ctx(session, character)
    _bus().publish(
        [
            GameEvent('move', {'to': 'Ruin Hall'}),
            GameEvent('gain_coins', {'amount': 50}),
            GameEvent('lose_coins', {'amount': 500}),  # more than owned → floor at 0
            GameEvent('add_status', {'status': 'poisoned'}),
            GameEvent('add_status', {'status': 'poisoned'}),  # idempotent
            GameEvent('level_up', {}),
        ],
        ctx,
    )
    character.refresh_from_db()
    assert character.current_location == 'Ruin Hall'
    assert character.coins == 0
    assert character.status_effects == ['poisoned']
    assert character.level == 2
    assert character.max_hp == 110 and character.hp == 110

    _bus().publish([GameEvent('remove_status', {'status': 'poisoned'})], ctx)
    character.refresh_from_db()
    assert character.status_effects == []


def test_inventory_observer_gain_and_lose(session, character):
    ctx = _ctx(session, character)
    _bus().publish([GameEvent('gain_item', {'item_name': 'Torch', 'quantity': 3})], ctx)
    assert InventoryItem.objects.get(character=character, item_name='Torch').quantity == 3

    _bus().publish([GameEvent('lose_item', {'item_name': 'Torch', 'quantity': 10})], ctx)
    assert not InventoryItem.objects.filter(character=character, item_name='Torch').exists()

    # losing an item you never had is a no-op, not an error
    _bus().publish([GameEvent('lose_item', {'item_name': 'Ghost', 'quantity': 1})], ctx)
    assert not InventoryItem.objects.filter(character=character).exists()


def test_quest_observer_lifecycle_pays_reward(session, character):
    ctx = _ctx(session, character)
    start = GameEvent('quest_start', {'title': 'Find the flame', 'description': 'd', 'reward_coins': 40})
    _bus().publish([start, start], ctx)  # duplicate start is ignored
    assert Quest.objects.filter(session=session).count() == 1

    # completing an unknown quest is a no-op
    _bus().publish([GameEvent('quest_complete', {'title': 'Nope', 'description': '', 'reward_coins': 0})], ctx)
    character.refresh_from_db()
    assert character.coins == 100

    _bus().publish([GameEvent('quest_complete', {'title': 'Find the flame', 'description': '', 'reward_coins': 0})], ctx)
    quest = Quest.objects.get(session=session)
    character.refresh_from_db()
    assert quest.status == Quest.STATUS_COMPLETED
    assert character.coins == 140

    # already-completed quest cannot be failed
    _bus().publish([GameEvent('quest_fail', {'title': 'Find the flame', 'description': '', 'reward_coins': 0})], ctx)
    quest.refresh_from_db()
    assert quest.status == Quest.STATUS_COMPLETED


# --- story service --------------------------------------------------------


def test_story_service_turn_applies_events_and_snapshots(session, character):
    ai_output = {
        'narrative': 'A goblin lunges from the shadows.',
        'events': [
            {'type': 'damage', 'amount': 12, 'source': 'goblin'},
            {'type': 'move', 'to': 'Ruin Hall'},
            {'type': 'gain_item', 'item_name': 'Goblin Ear', 'quantity': 1},
            {'type': 'quest_start', 'title': 'Clear the hall', 'description': '', 'reward_coins': 20},
            {'type': 'bogus'},
        ],
    }
    with patch('game.services.story_service.OpenAIService.generate_story_turn', return_value=ai_output) as gen, patch(
        'game.services.story_service.MongoService.insert_conversation_log', return_value={'ok': True}
    ), patch('game.services.story_service.MongoService.get_conversation_history', return_value=[]), patch(
        'game.services.events.MongoService.insert_event_log', return_value={'ok': True}
    ) as event_log:
        result = StoryService().play_turn(session=session, user_input='I enter.')

    assert result.narrative == ai_output['narrative']
    assert [e.type for e in result.events] == ['damage', 'move', 'gain_item', 'quest_start']
    assert event_log.call_count == 4
    assert result.state['hp'] == 88
    assert result.state['location'] == 'Ruin Hall'
    assert result.state['inventory'] == [{'item_name': 'Goblin Ear', 'quantity': 1}]
    assert result.state['quests'] == [{'title': 'Clear the hall', 'status': 'active', 'reward_coins': 20}]
    # the model is told the pre-turn state
    assert gen.call_args.kwargs['state']['hp'] == 100


# --- openai output parsing ------------------------------------------------


def _fake_ai(text):
    from unittest.mock import MagicMock

    from game.services.openai_service import OpenAIService

    svc = OpenAIService.__new__(OpenAIService)
    svc._client = MagicMock()
    svc._client.responses.create.return_value = MagicMock(output_text=text)
    return svc


def _turn(svc):
    return svc.generate_story_turn(
        world_name='W', world_lore_summary='L', character_name='C', character_role='R', user_input='go'
    )


def test_generate_story_turn_parses_json_envelope():
    out = _turn(_fake_ai('```json\n{"narrative": "Hi.", "events": [{"type": "heal", "amount": 5}]}\n```'))
    assert out == {'narrative': 'Hi.', 'events': [{'type': 'heal', 'amount': 5}]}


def test_generate_story_turn_falls_back_to_plain_text():
    out = _turn(_fake_ai('The wind howls through the ruins.'))
    assert out == {'narrative': 'The wind howls through the ruins.', 'events': []}


def test_generate_story_turn_tolerates_bad_events_field():
    out = _turn(_fake_ai('{"narrative": "Hi.", "events": "none"}'))
    assert out['events'] == []
