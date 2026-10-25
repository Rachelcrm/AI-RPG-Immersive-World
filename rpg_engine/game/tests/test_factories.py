from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from game.models import Encounter, Location, MarketItem, NPC
from game.services.events import EventRuleLayer, GameEvent, GameStateBus, SpawnObserver, TurnContext
from game.services.factories import (
    ComponentFactoryRegistry,
    EncounterFactory,
    GameComponentFactory,
    ItemFactory,
    LocationFactory,
    NPCFactory,
)
from game.services.openai_service import OpenAIService
from game.services.story_service import StoryService

pytestmark = pytest.mark.django_db


# --- registry -------------------------------------------------------------


def test_registry_lists_and_resolves_kinds():
    assert ComponentFactoryRegistry.kinds() == ['encounter', 'item', 'location', 'npc']
    assert isinstance(ComponentFactoryRegistry.get('npc'), NPCFactory)
    with pytest.raises(ValueError):
        ComponentFactoryRegistry.get('dragon')


def test_registry_accepts_new_factory_kind(world):
    class RumorFactory(GameComponentFactory):
        kind = 'rumor'

        def schema_hint(self):
            return '{"text": str}'

        def validate(self, spec, *, world):
            return {'text': spec['text']} if spec.get('text') else None

        def build(self, *, world, session, spec):
            return spec['text'].upper()

    ComponentFactoryRegistry.register(RumorFactory)
    try:
        assert ComponentFactoryRegistry.get('rumor').create(world=world, spec={'text': 'hi'}) == 'HI'
    finally:
        ComponentFactoryRegistry._factories.pop('rumor')


# --- concrete factories (spec supplied, no AI) ----------------------------


def test_location_factory_validates_and_appends_to_world(world):
    loc = LocationFactory().create(
        world=world, spec={'name': ' Sunken Vault ', 'danger_level': 99, 'tags': ['dark', '', 7]}
    )
    assert loc.name == 'Sunken Vault'
    assert loc.danger_level == 5
    assert loc.tags == ['dark', '7']
    world.refresh_from_db()
    assert 'Sunken Vault' in world.locations

    # same name is an upsert, not a duplicate
    LocationFactory().create(world=world, spec={'name': 'Sunken Vault', 'description': 'wet'})
    assert Location.objects.filter(world=world, name='Sunken Vault').count() == 1
    assert Location.objects.get(world=world, name='Sunken Vault').description == 'wet'


def test_location_factory_rejects_nameless_spec(world):
    with pytest.raises(ValueError):
        LocationFactory().create(world=world, spec={'description': 'nothing'})


def test_npc_factory_defaults_bad_disposition(world):
    npc = NPCFactory().create(world=world, spec={'name': 'Mira', 'role': 'Smith', 'disposition': 'angry'})
    assert npc.disposition == 'neutral'
    assert NPC.objects.filter(world=world, name='Mira').exists()


def test_item_factory_reuses_market_rule_layer(world):
    item = ItemFactory().create(world=world, spec={'name': 'Ash Blade', 'rarity': 'legendary', 'base_price': '42.5'})
    assert isinstance(item, MarketItem)
    assert item.base_price == Decimal('42.50')
    assert item.rarity in {'common', 'rare', 'epic'}


def test_encounter_factory_requires_session(world, session):
    with pytest.raises(ValueError, match='session'):
        EncounterFactory().create(world=world, spec={'title': 'Ambush'})
    enc = EncounterFactory().create(world=world, session=session, spec={'title': 'Ambush', 'kind': 'combat', 'difficulty': 0})
    assert enc.kind == 'combat'
    assert enc.difficulty == 1
    assert enc.session_id == session.id


# --- AI-driven generation ------------------------------------------------


def test_create_many_uses_ai_specs_and_skips_invalid(world):
    ai = MagicMock()
    ai.generate_components.return_value = [
        {'name': 'Garr', 'role': 'Guard', 'disposition': 'hostile'},
        {'role': 'nameless'},
        {'name': 'Pell', 'role': 'Trader', 'location': 'Ash Market'},
    ]
    npcs = NPCFactory(ai=ai).create_many(world=world, count=3, hint='market folk')
    assert [n.name for n in npcs] == ['Garr', 'Pell']
    kwargs = ai.generate_components.call_args.kwargs
    assert kwargs['kind'] == 'npc'
    assert kwargs['count'] == 3
    assert kwargs['hint'] == 'market folk'
    assert kwargs['known_locations'] == ['Ruin Hall', 'Ash Market']


def test_create_many_clamps_count(world):
    ai = MagicMock()
    ai.generate_components.return_value = []
    NPCFactory(ai=ai).create_many(world=world, count=999)
    assert ai.generate_components.call_args.kwargs['count'] == NPCFactory.max_batch


def _fake_ai(text):
    svc = OpenAIService.__new__(OpenAIService)
    svc._client = MagicMock()
    svc._client.responses.create.return_value = MagicMock(output_text=text)
    return svc


@pytest.mark.parametrize(
    'text',
    [
        '[{"name": "A"}, {"name": "B"}]',
        '```json\n[{"name": "A"}, {"name": "B"}]\n```',
        '{"npcs": [{"name": "A"}, {"name": "B"}]}',
        '[{"name": "A"}, "junk", {"name": "B"}]',
    ],
)
def test_generate_components_parses_array_shapes(text):
    out = _fake_ai(text).generate_components(
        kind='npc', schema='{}', world_name='W', world_lore_summary='L', known_locations=[], count=2
    )
    assert out == [{'name': 'A'}, {'name': 'B'}]


def test_generate_components_rejects_garbage():
    with pytest.raises(ValueError):
        _fake_ai('no json here').generate_components(
            kind='npc', schema='{}', world_name='W', world_lore_summary='L', known_locations=[], count=1
        )


# --- spawn event: Observer -> Factory ---------------------------------------


def test_rule_layer_normalizes_spawn_events():
    events = EventRuleLayer.sanitize(
        [
            {'type': 'spawn', 'kind': 'npc', 'name': 'Garr', 'role': 'Guard'},
            {'type': 'spawn', 'kind': 'encounter', 'encounter_kind': 'combat', 'title': 'Ambush'},
            {'type': 'spawn', 'kind': 'dragon', 'name': 'x'},
            {'type': 'spawn'},
        ]
    )
    assert [e.to_dict() for e in events] == [
        {'type': 'spawn', 'kind': 'npc', 'spec': {'name': 'Garr', 'role': 'Guard'}},
        {'type': 'spawn', 'kind': 'encounter', 'spec': {'kind': 'combat', 'title': 'Ambush'}},
    ]


def test_spawn_observer_creates_components_and_ignores_invalid(session, character, world):
    ctx = TurnContext(session=session, character=character, user_input='x', narrative='y')
    bus = GameStateBus().subscribe(SpawnObserver())
    bus.publish(
        [
            GameEvent('spawn', {'kind': 'npc', 'spec': {'name': 'Garr', 'role': 'Guard', 'disposition': 'hostile'}}),
            GameEvent('spawn', {'kind': 'encounter', 'spec': {'title': 'Ambush', 'kind': 'combat', 'difficulty': 3}}),
            GameEvent('spawn', {'kind': 'location', 'spec': {'name': 'Sunken Vault'}}),
            GameEvent('spawn', {'kind': 'npc', 'spec': {'role': 'no name'}}),
        ],
        ctx,
    )
    assert NPC.objects.get(world=world, name='Garr').disposition == 'hostile'
    assert Encounter.objects.get(session=session, title='Ambush').difficulty == 3
    assert Location.objects.filter(world=world, name='Sunken Vault').exists()
    assert ctx.notes == ['New npc: Garr.', 'New encounter: Ambush.', 'New location: Sunken Vault.']


def test_story_snapshot_includes_world_components(session, character, world):
    character.current_location = 'Ash Market'
    character.save()
    NPCFactory().create(world=world, spec={'name': 'Pell', 'role': 'Trader', 'location': 'Ash Market'})
    NPCFactory().create(world=world, spec={'name': 'Far', 'role': 'Hermit', 'location': 'Ruin Hall'})
    EncounterFactory().create(world=world, session=session, spec={'title': 'Haggle', 'kind': 'social'})

    snap = StoryService.state_snapshot(character, session)
    assert snap['known_locations'] == ['Ruin Hall', 'Ash Market']
    assert [n['name'] for n in snap['nearby_npcs']] == ['Pell']
    assert snap['active_encounters'] == [{'kind': 'social', 'title': 'Haggle', 'difficulty': 1}]


# --- endpoints -------------------------------------------------------------


def test_world_generate_populates_locations_and_npcs(api, book):
    fake_world = {
        'world_name': 'Ashen Realm',
        'lore_summary': 'ash',
        'factions': ['A'],
        'locations': ['Ruin Hall', 'Ash Market'],
        'main_conflict': 'C',
    }
    with patch('game.views.OpenAIService.generate_world', return_value=fake_world), patch(
        'game.services.factories.OpenAIService.generate_components',
        return_value=[{'name': 'Garr', 'role': 'Guard'}],
    ):
        resp = api.post('/api/worlds/generate/', {'book_id': book.id}, format='json')
    assert resp.status_code == 201
    body = resp.json()
    assert [l['name'] for l in body['locations']] == ['Ruin Hall', 'Ash Market']
    assert [n['name'] for n in body['npcs']] == ['Garr']
    assert body['npc_error'] is None
    assert Location.objects.filter(world_id=body['world']['id']).count() == 2


def test_world_generate_survives_npc_generation_failure(api, book):
    fake_world = {'world_name': 'W', 'lore_summary': '', 'factions': [], 'locations': ['X'], 'main_conflict': ''}
    with patch('game.views.OpenAIService.generate_world', return_value=fake_world), patch(
        'game.services.factories.OpenAIService.generate_components', side_effect=ValueError('no key')
    ):
        resp = api.post('/api/worlds/generate/', {'book_id': book.id}, format='json')
    assert resp.status_code == 201
    assert resp.json()['npcs'] == []
    assert resp.json()['npc_error'] == 'no key'


def test_component_endpoint_with_spec(api, world):
    resp = api.post(
        f'/api/worlds/{world.id}/components/generate/',
        {'kind': 'npc', 'spec': {'name': 'Mira', 'role': 'Smith'}},
        format='json',
    )
    assert resp.status_code == 201
    assert resp.json()['components'][0]['name'] == 'Mira'


def test_component_endpoint_with_ai(api, world):
    with patch(
        'game.services.factories.OpenAIService.generate_components',
        return_value=[{'name': 'Sunken Vault', 'danger_level': 4}],
    ):
        resp = api.post(
            f'/api/worlds/{world.id}/components/generate/', {'kind': 'location', 'count': 1}, format='json'
        )
    assert resp.status_code == 201
    assert resp.json()['components'][0]['danger_level'] == 4


def test_component_endpoint_errors(api, world, session):
    assert api.post(f'/api/worlds/{world.id}/components/generate/', {'kind': 'encounter'}, format='json').status_code == 400
    assert api.post('/api/worlds/999/components/generate/', {'kind': 'npc'}, format='json').status_code == 404
    assert (
        api.post(
            f'/api/worlds/{world.id}/components/generate/', {'kind': 'npc', 'spec': {'role': 'x'}}, format='json'
        ).status_code
        == 400
    )
    with patch('game.services.factories.OpenAIService.generate_components', side_effect=RuntimeError('down')):
        resp = api.post(f'/api/worlds/{world.id}/components/generate/', {'kind': 'npc'}, format='json')
    assert resp.status_code == 502
