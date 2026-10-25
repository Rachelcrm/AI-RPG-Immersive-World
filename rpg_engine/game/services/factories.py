"""Factory Method for game components.

GameComponentFactory defines the creation pipeline (spec -> validate -> build)
and leaves the component-specific steps to subclasses. Specs can come from
the AI (generate_specs), from a narrative event (spawn), or from a caller.
New component kinds register themselves with ComponentFactoryRegistry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from game.models import Encounter, Location, MarketItem, NPC, StorySession, World
from game.services.openai_service import OpenAIService
from game.services.rule_layer import MarketRuleLayer


def _clamp_int(value, *, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(Decimal(str(value)))))
    except Exception:
        return default


def _text(value, *, limit: int, default: str = '') -> str:
    text = str(value if value is not None else default).strip()
    return text[:limit] if text else default


class GameComponentFactory(ABC):
    kind: str = ''
    max_batch = 10

    def __init__(self, *, ai: OpenAIService | None = None) -> None:
        self._ai = ai

    # --- template method -------------------------------------------------

    def create(self, *, world: World, spec: dict | None = None, session: StorySession | None = None, hint: str = ''):
        if spec is None:
            specs = self.generate_specs(world=world, count=1, hint=hint)
            if not specs:
                raise ValueError(f'No {self.kind} spec could be generated.')
            spec = specs[0]
        validated = self.validate(spec, world=world)
        if validated is None:
            raise ValueError(f'Invalid {self.kind} spec: {spec!r}')
        return self.build(world=world, session=session, spec=validated)

    def create_many(self, *, world: World, count: int, session: StorySession | None = None, hint: str = '') -> list:
        count = max(1, min(self.max_batch, count))
        created = []
        for spec in self.generate_specs(world=world, count=count, hint=hint)[:count]:
            validated = self.validate(spec, world=world)
            if validated is not None:
                created.append(self.build(world=world, session=session, spec=validated))
        return created

    def generate_specs(self, *, world: World, count: int, hint: str) -> list[dict]:
        ai = self._ai or OpenAIService()
        return ai.generate_components(
            kind=self.kind,
            schema=self.schema_hint(),
            world_name=world.name,
            world_lore_summary=world.lore_summary,
            known_locations=list(world.locations or []),
            count=count,
            hint=hint,
        )

    # --- hooks for subclasses -------------------------------------------

    @abstractmethod
    def schema_hint(self) -> str:
        """One-line JSON shape shown to the model."""

    @abstractmethod
    def validate(self, spec: dict, *, world: World) -> dict | None:
        """Return a cleaned spec, or None to reject it."""

    @abstractmethod
    def build(self, *, world: World, session: StorySession | None, spec: dict):
        """Persist and return the component."""


class LocationFactory(GameComponentFactory):
    kind = 'location'

    def schema_hint(self) -> str:
        return '{"name": str, "description": str, "danger_level": 1-5, "tags": [str]}'

    def validate(self, spec: dict, *, world: World) -> dict | None:
        name = _text(spec.get('name'), limit=120)
        if not name:
            return None
        tags = spec.get('tags')
        return {
            'name': name,
            'description': _text(spec.get('description'), limit=1000),
            'danger_level': _clamp_int(spec.get('danger_level'), lo=1, hi=5, default=1),
            'tags': [_text(t, limit=40) for t in tags if _text(t, limit=40)][:8] if isinstance(tags, list) else [],
        }

    def build(self, *, world: World, session: StorySession | None, spec: dict) -> Location:
        location, _ = Location.objects.update_or_create(
            world=world,
            name=spec['name'],
            defaults={'description': spec['description'], 'danger_level': spec['danger_level'], 'tags': spec['tags']},
        )
        if spec['name'] not in (world.locations or []):
            world.locations = [*(world.locations or []), spec['name']]
            world.save(update_fields=['locations', 'updated_at'])
        return location


class NPCFactory(GameComponentFactory):
    kind = 'npc'
    _dispositions = {d for d, _ in NPC.DISPOSITION_CHOICES}

    def schema_hint(self) -> str:
        return '{"name": str, "role": str, "faction": str, "location": str, "disposition": "friendly|neutral|hostile", "description": str}'

    def validate(self, spec: dict, *, world: World) -> dict | None:
        name = _text(spec.get('name'), limit=120)
        if not name:
            return None
        disposition = _text(spec.get('disposition'), limit=20, default='neutral').lower()
        return {
            'name': name,
            'role': _text(spec.get('role'), limit=80),
            'faction': _text(spec.get('faction'), limit=120),
            'location': _text(spec.get('location'), limit=120),
            'disposition': disposition if disposition in self._dispositions else 'neutral',
            'description': _text(spec.get('description'), limit=1000),
        }

    def build(self, *, world: World, session: StorySession | None, spec: dict) -> NPC:
        npc, _ = NPC.objects.update_or_create(world=world, name=spec['name'], defaults={**spec, 'is_alive': True})
        return npc


class ItemFactory(GameComponentFactory):
    """Creates MarketItems; reuses the market rule layer so prices stay sane."""

    kind = 'item'

    def schema_hint(self) -> str:
        return '{"name": str, "category": str, "rarity": "common|rare|epic", "base_price": number}'

    def validate(self, spec: dict, *, world: World) -> dict | None:
        cleaned = MarketRuleLayer.sanitize_items([{**spec, 'stock': spec.get('stock', 1)}])
        return cleaned[0] if cleaned else None

    def build(self, *, world: World, session: StorySession | None, spec: dict) -> MarketItem:
        item, _ = MarketItem.objects.update_or_create(
            world=world,
            name=spec['name'],
            defaults={'category': spec['category'], 'rarity': spec['rarity'], 'base_price': spec['base_price']},
        )
        return item


class EncounterFactory(GameComponentFactory):
    kind = 'encounter'
    _kinds = {k for k, _ in Encounter.KIND_CHOICES}

    def schema_hint(self) -> str:
        return '{"kind": "combat|social|puzzle|discovery", "title": str, "description": str, "location": str, "difficulty": 1-5}'

    def validate(self, spec: dict, *, world: World) -> dict | None:
        title = _text(spec.get('title'), limit=160)
        if not title:
            return None
        kind = _text(spec.get('kind'), limit=20, default='discovery').lower()
        return {
            'kind': kind if kind in self._kinds else 'discovery',
            'title': title,
            'description': _text(spec.get('description'), limit=1000),
            'location': _text(spec.get('location'), limit=120),
            'difficulty': _clamp_int(spec.get('difficulty'), lo=1, hi=5, default=1),
        }

    def build(self, *, world: World, session: StorySession | None, spec: dict) -> Encounter:
        if session is None:
            raise ValueError('Encounters belong to a session.')
        return Encounter.objects.create(session=session, **spec)


class ComponentFactoryRegistry:
    _factories: dict[str, type[GameComponentFactory]] = {}

    @classmethod
    def register(cls, factory_cls: type[GameComponentFactory]) -> type[GameComponentFactory]:
        cls._factories[factory_cls.kind] = factory_cls
        return factory_cls

    @classmethod
    def kinds(cls) -> list[str]:
        return sorted(cls._factories)

    @classmethod
    def get(cls, kind: str, *, ai: OpenAIService | None = None) -> GameComponentFactory:
        factory_cls = cls._factories.get(kind)
        if factory_cls is None:
            raise ValueError(f'Unknown component kind: {kind}')
        return factory_cls(ai=ai)


for _factory in (LocationFactory, NPCFactory, ItemFactory, EncounterFactory):
    ComponentFactoryRegistry.register(_factory)
