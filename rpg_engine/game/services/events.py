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
}

MAX_DAMAGE_PER_TURN = 60
MAX_HEAL_PER_TURN = 60
MAX_COINS_PER_TURN = 500
MAX_ITEM_QTY_PER_TURN = 10


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
            elif kind == 'level_up':
                events.append(GameEvent(kind, {}))
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
            ctx.notes.append(f'{c.name} takes {p["amount"]} damage (HP {c.hp}/{c.max_hp}).')
            if c.hp == 0:
                ctx.notes.append(f'{c.name} has fallen.')
        elif event.type == 'heal':
            c.hp = min(c.max_hp, c.hp + p['amount'])
            ctx.notes.append(f'{c.name} recovers {p["amount"]} HP (HP {c.hp}/{c.max_hp}).')
        elif event.type == 'move':
            c.current_location = p['to']
            ctx.notes.append(f'{c.name} moves to {p["to"]}.')
        elif event.type == 'gain_coins':
            c.coins += p['amount']
            ctx.notes.append(f'+{p["amount"]} coins (now {c.coins}).')
        elif event.type == 'lose_coins':
            lost = min(c.coins, p['amount'])
            c.coins -= lost
            ctx.notes.append(f'-{lost} coins (now {c.coins}).')
        elif event.type == 'add_status':
            if p['status'] not in c.status_effects:
                c.status_effects = [*c.status_effects, p['status']]
                ctx.notes.append(f'{c.name} is now {p["status"]}.')
        elif event.type == 'remove_status':
            if p['status'] in c.status_effects:
                c.status_effects = [s for s in c.status_effects if s != p['status']]
                ctx.notes.append(f'{c.name} is no longer {p["status"]}.')
        elif event.type == 'level_up':
            c.level += 1
            c.max_hp += 10
            c.hp = c.max_hp
            ctx.notes.append(f'{c.name} reaches level {c.level}!')
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
            ctx.notes.append(f'Obtained {name} x{qty}.')
        else:
            removed = min(item.quantity, qty)
            item.quantity -= removed
            if item.quantity == 0:
                item.delete()
            else:
                item.save(update_fields=['quantity', 'updated_at'])
            if removed:
                ctx.notes.append(f'Lost {name} x{removed}.')


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
                ctx.notes.append(f'New quest: {p["title"]}.')
            return

        quest = Quest.objects.filter(session=ctx.session, title=p['title'], status=Quest.STATUS_ACTIVE).first()
        if quest is None:
            return
        if event.type == 'quest_complete':
            quest.status = Quest.STATUS_COMPLETED
            if quest.reward_coins:
                ctx.character.coins += quest.reward_coins
                ctx.character.save(update_fields=['coins', 'updated_at'])
            ctx.notes.append(f'Quest complete: {quest.title} (+{quest.reward_coins} coins).')
        else:
            quest.status = Quest.STATUS_FAILED
            ctx.notes.append(f'Quest failed: {quest.title}.')
        quest.save(update_fields=['status', 'updated_at'])


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
        .subscribe(MongoEventObserver())
    )
