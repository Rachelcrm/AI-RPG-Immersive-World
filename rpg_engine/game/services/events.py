"""Observer pattern for real-time game state.

The narrative engine emits structured GameEvents each turn. A GameStateBus
publishes them to registered observers, each of which owns one slice of
state (character stats, inventory, quests, logging). Adding a new kind of
state reaction means adding a new observer, not touching the interact view.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from game.models import Character, InventoryItem, Quest, StorySession
from game.services.mongo_service import MongoService
from django.conf import settings

# Event types the rule layer accepts. Anything else from the model is dropped.
EVENT_TYPES = {
    'damage',
    'heal',
    'move',
    'gain_coins',
    'lose_coins',
    'gain_item',
    'lose_item',
    'add_status',
    'remove_status',
    'quest_start',
    'quest_complete',
    'quest_fail',
    'level_up',
    'spawn',
    'next_chapter',
}
SPAWNABLE_KINDS = {'npc', 'encounter', 'location'}

MAX_DAMAGE_PER_TURN = 60
MAX_HEAL_PER_TURN = 60
MAX_COINS_PER_TURN = 500
MAX_ITEM_QTY_PER_TURN = 10



# Player-facing turn notes, in the configured output language (English templates are the fallback).
NOTE_TEMPLATES = {
    'en': {
        'damage': '{name} takes {amount} damage (HP {hp}/{max_hp}).',
        'fallen': '{name} has fallen.',
        'heal': '{name} recovers {amount} HP (HP {hp}/{max_hp}).',
        'move': '{name} moves to {to}.',
        'gain_coins': '+{amount} coins (now {coins}).',
        'lose_coins': '-{amount} coins (now {coins}).',
        'add_status': '{name} is now {status}.',
        'remove_status': '{name} is no longer {status}.',
        'level_up': '{name} reaches level {level}!',
        'gain_item': 'Obtained {name} x{qty}.',
        'lose_item': 'Lost {name} x{qty}.',
        'quest_start': 'New quest: {title}.',
        'quest_complete': 'Quest complete: {title} (+{coins} coins).',
        'quest_fail': 'Quest failed: {title}.',
        'spawn': 'New {kind}: {label}.',
        'next_chapter': 'The story moves on to chapter {chapter}.',
        'story_end': 'The story ends here.',
    },
    'zh': {
        'damage': '{name} 受到 {amount} 点伤害（HP {hp}/{max_hp}）。',
        'fallen': '{name} 倒下了。',
        'heal': '{name} 恢复 {amount} 点生命（HP {hp}/{max_hp}）。',
        'move': '{name} 来到了 {to}。',
        'gain_coins': '金币 +{amount}（现有 {coins}）。',
        'lose_coins': '金币 -{amount}（现有 {coins}）。',
        'add_status': '{name} 进入状态：{status}。',
        'remove_status': '{name} 解除状态：{status}。',
        'level_up': '{name} 升到了 {level} 级！',
        'gain_item': '获得 {name} ×{qty}。',
        'lose_item': '失去 {name} ×{qty}。',
        'quest_start': '新任务：{title}。',
        'quest_complete': '任务完成：{title}（金币 +{coins}）。',
        'quest_fail': '任务失败：{title}。',
        'spawn': '新登场{kind}：{label}。',
        'next_chapter': '故事进入第 {chapter} 章。',
        'story_end': '故事到此为止。',
    },
}
_KIND_ZH = {'npc': '人物', 'encounter': '遭遇', 'location': '地点', 'item': '物品'}


def note(key: str, **kw) -> str:
    lang = 'zh' if str(settings.RPG_OUTPUT_LANGUAGE).lower().startswith(('chinese', 'zh', '中文')) else 'en'
    if lang == 'zh' and 'kind' in kw:
        kw['kind'] = _KIND_ZH.get(kw['kind'], kw['kind'])
    return NOTE_TEMPLATES[lang][key].format(**kw)

@dataclass
class GameEvent:
    type: str
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {'type': self.type, **self.payload}


@dataclass
class TurnContext:
    session: StorySession
    character: Character
    user_input: str
    narrative: str
    # Observers append human-readable notes here; returned to the client.
    notes: list[str] = field(default_factory=list)


class EventRuleLayer:
    """Validate and clamp model-emitted events before they touch state."""

    @staticmethod
    def _int(value, *, lo: int, hi: int, default: int = 0) -> int:
        try:
            number = int(Decimal(str(value)))
        except Exception:
            return default
        return max(lo, min(hi, number))

    @classmethod
    def sanitize(cls, raw_events: list) -> list[GameEvent]:
        events: list[GameEvent] = []
        if not isinstance(raw_events, list):
            return events
        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get('type', '')).strip().lower()
            if kind not in EVENT_TYPES:
                continue

            if kind == 'damage':
                amount = cls._int(raw.get('amount'), lo=0, hi=MAX_DAMAGE_PER_TURN)
                if amount:
                    events.append(GameEvent(kind, {'amount': amount, 'source': str(raw.get('source', ''))[:120]}))
            elif kind == 'heal':
                amount = cls._int(raw.get('amount'), lo=0, hi=MAX_HEAL_PER_TURN)
                if amount:
                    events.append(GameEvent(kind, {'amount': amount}))
            elif kind == 'move':
                to = str(raw.get('to', '')).strip()[:120]
                if to:
                    events.append(GameEvent(kind, {'to': to}))
            elif kind in {'gain_coins', 'lose_coins'}:
                amount = cls._int(raw.get('amount'), lo=0, hi=MAX_COINS_PER_TURN)
                if amount:
                    events.append(GameEvent(kind, {'amount': amount}))
            elif kind in {'gain_item', 'lose_item'}:
                name = str(raw.get('item_name', '')).strip()[:120]
                qty = cls._int(raw.get('quantity', 1), lo=1, hi=MAX_ITEM_QTY_PER_TURN, default=1)
                if name:
                    events.append(GameEvent(kind, {'item_name': name, 'quantity': qty}))
            elif kind in {'add_status', 'remove_status'}:
                status = str(raw.get('status', '')).strip().lower()[:40]
                if status:
                    events.append(GameEvent(kind, {'status': status}))
            elif kind in {'quest_start', 'quest_complete', 'quest_fail'}:
                title = str(raw.get('title', '')).strip()[:160]
                if title:
                    events.append(
                        GameEvent(
                            kind,
                            {
                                'title': title,
                                'description': str(raw.get('description', ''))[:1000],
                                'reward_coins': cls._int(raw.get('reward_coins', 0), lo=0, hi=MAX_COINS_PER_TURN),
                            },
                        )
                    )
            elif kind in {'level_up', 'next_chapter'}:
                events.append(GameEvent(kind, {}))
            elif kind == 'spawn':
                spawn_kind = str(raw.get('kind', '')).strip().lower()
                if spawn_kind not in SPAWNABLE_KINDS:
                    continue
                # Everything else in the dict is the component spec; the
                # factory's own validate() cleans it.
                spec = {k: v for k, v in raw.items() if k not in {'type', 'kind'}}
                if spawn_kind == 'encounter' and 'encounter_kind' in spec:
                    spec['kind'] = spec.pop('encounter_kind')
                events.append(GameEvent(kind, {'kind': spawn_kind, 'spec': spec}))
        return events


class GameObserver(Protocol):
    def handles(self) -> set[str]: ...

    def on_event(self, event: GameEvent, ctx: TurnContext) -> None: ...


class GameStateBus:
    def __init__(self) -> None:
        self._observers: list[GameObserver] = []

    def subscribe(self, observer: GameObserver) -> GameStateBus:
        self._observers.append(observer)
        return self

    def publish(self, events: list[GameEvent], ctx: TurnContext) -> list[GameEvent]:
        applied: list[GameEvent] = []
        for event in events:
            for observer in self._observers:
                if event.type in observer.handles():
                    observer.on_event(event, ctx)
            applied.append(event)
        return applied


class CharacterObserver:
    """HP, location, coins, status effects, level."""

    def handles(self) -> set[str]:
        return {'damage', 'heal', 'move', 'gain_coins', 'lose_coins', 'add_status', 'remove_status', 'level_up'}

    def on_event(self, event: GameEvent, ctx: TurnContext) -> None:
        c = ctx.character
        p = event.payload
        if event.type == 'damage':
            c.hp = max(0, c.hp - p['amount'])
            ctx.notes.append(note('damage', name=c.name, amount=p['amount'], hp=c.hp, max_hp=c.max_hp))
            if c.hp == 0:
                ctx.notes.append(note('fallen', name=c.name))
        elif event.type == 'heal':
            c.hp = min(c.max_hp, c.hp + p['amount'])
            ctx.notes.append(note('heal', name=c.name, amount=p['amount'], hp=c.hp, max_hp=c.max_hp))
        elif event.type == 'move':
            c.current_location = p['to']
            ctx.notes.append(note('move', name=c.name, to=p['to']))
        elif event.type == 'gain_coins':
            c.coins = c.coins + p['amount']
            ctx.notes.append(note('gain_coins', amount=p['amount'], coins=c.coins))
        elif event.type == 'lose_coins':
            lost = min(c.coins, Decimal(p['amount']))
            c.coins = c.coins - lost
            ctx.notes.append(note('lose_coins', amount=lost, coins=c.coins))
        elif event.type == 'add_status':
            if p['status'] not in c.status_effects:
                c.status_effects = [*c.status_effects, p['status']]
                ctx.notes.append(note('add_status', name=c.name, status=p['status']))
        elif event.type == 'remove_status':
            if p['status'] in c.status_effects:
                c.status_effects = [s for s in c.status_effects if s != p['status']]
                ctx.notes.append(note('remove_status', name=c.name, status=p['status']))
        elif event.type == 'level_up':
            c.level += 1
            c.max_hp += 10
            c.hp = c.max_hp
            ctx.notes.append(note('level_up', name=c.name, level=c.level))
        c.save(update_fields=['hp', 'max_hp', 'current_location', 'coins', 'status_effects', 'level', 'updated_at'])


class InventoryObserver:
    def handles(self) -> set[str]:
        return {'gain_item', 'lose_item'}

    def on_event(self, event: GameEvent, ctx: TurnContext) -> None:
        name, qty = event.payload['item_name'], event.payload['quantity']
        item, _ = InventoryItem.objects.get_or_create(
            character=ctx.character, item_name=name, defaults={'quantity': 0, 'avg_unit_price': Decimal('0.00')}
        )
        if event.type == 'gain_item':
            item.quantity += qty
            item.save(update_fields=['quantity', 'updated_at'])
            ctx.notes.append(note('gain_item', name=name, qty=qty))
        else:
            removed = min(item.quantity, qty)
            item.quantity -= removed
            if item.quantity == 0:
                item.delete()
            else:
                item.save(update_fields=['quantity', 'updated_at'])
            if removed:
                ctx.notes.append(note('lose_item', name=name, qty=removed))


class QuestObserver:
    """Quest lifecycle; completing a quest pays its reward via the character."""

    def handles(self) -> set[str]:
        return {'quest_start', 'quest_complete', 'quest_fail'}

    def on_event(self, event: GameEvent, ctx: TurnContext) -> None:
        p = event.payload
        if event.type == 'quest_start':
            _, created = Quest.objects.get_or_create(
                session=ctx.session,
                title=p['title'],
                defaults={
                    'character': ctx.character,
                    'description': p['description'],
                    'reward_coins': p['reward_coins'],
                },
            )
            if created:
                ctx.notes.append(note('quest_start', title=p['title']))
            return

        quest = Quest.objects.filter(session=ctx.session, title=p['title'], status=Quest.STATUS_ACTIVE).first()
        if quest is None:
            return
        if event.type == 'quest_complete':
            quest.status = Quest.STATUS_COMPLETED
            if quest.reward_coins:
                ctx.character.coins = ctx.character.coins + quest.reward_coins
                ctx.character.save(update_fields=['coins', 'updated_at'])
            ctx.notes.append(note('quest_complete', title=quest.title, coins=quest.reward_coins))
        else:
            quest.status = Quest.STATUS_FAILED
            ctx.notes.append(note('quest_fail', title=quest.title))
        quest.save(update_fields=['status', 'updated_at'])


class SpawnObserver:
    """Creates new game components mid-story through the component factories."""

    def handles(self) -> set[str]:
        return {'spawn'}

    def on_event(self, event: GameEvent, ctx: TurnContext) -> None:
        from game.services.factories import ComponentFactoryRegistry

        kind, spec = event.payload['kind'], event.payload['spec']
        try:
            factory = ComponentFactoryRegistry.get(kind)
            component = factory.create(world=ctx.session.world, spec=spec, session=ctx.session)
        except ValueError:
            return  # invalid spec: skip silently, narrative already happened
        label = getattr(component, 'title', None) or getattr(component, 'name', '')
        event.payload['id'] = component.id
        ctx.notes.append(note('spawn', kind=kind, label=label))


class ChapterObserver:
    """Advances the session through the source book's chapters."""

    def handles(self) -> set[str]:
        return {'next_chapter'}

    def on_event(self, event: GameEvent, ctx: TurnContext) -> None:
        session = ctx.session
        book = session.world.book
        last = book.chapter_count if book is not None and book.chapter_count else None
        if last is not None and session.current_chapter >= last:
            return
        session.current_chapter += 1
        session.save(update_fields=['current_chapter', 'updated_at'])
        ctx.notes.append(note('next_chapter', chapter=session.current_chapter))


class MongoEventObserver:
    """Persists every applied event to MongoDB as part of the interaction history."""

    def handles(self) -> set[str]:
        return EVENT_TYPES

    def on_event(self, event: GameEvent, ctx: TurnContext) -> None:
        MongoService.insert_event_log(
            session_id=ctx.session.id,
            character_id=ctx.character.id,
            event=event.to_dict(),
        )


def build_default_bus() -> GameStateBus:
    return (
        GameStateBus()
        .subscribe(CharacterObserver())
        .subscribe(InventoryObserver())
        .subscribe(QuestObserver())
        .subscribe(SpawnObserver())
        .subscribe(ChapterObserver())
        .subscribe(MongoEventObserver())
    )
