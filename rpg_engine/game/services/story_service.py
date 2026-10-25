from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from game.models import Character, Encounter, InventoryItem, NPC, Quest, StorySession
from game.services.events import EventRuleLayer, GameEvent, GameStateBus, TurnContext, build_default_bus
from game.services.mongo_service import MongoService
from game.services.openai_service import OpenAIService


@dataclass
class TurnResult:
    narrative: str
    events: list[GameEvent]
    notes: list[str]
    state: dict
    history_saved: bool


class StoryService:
    """One game turn: narrate, sanitize events, publish to observers, snapshot state."""

    def __init__(self, *, bus: GameStateBus | None = None, ai: OpenAIService | None = None) -> None:
        self._bus = bus or build_default_bus()
        self._ai = ai or OpenAIService()

    @staticmethod
    def state_snapshot(character: Character, session: StorySession) -> dict:
        inventory = InventoryItem.objects.filter(character=character).order_by('item_name')
        quests = Quest.objects.filter(session=session).order_by('id')
        nearby_npcs = NPC.objects.filter(world=session.world, is_alive=True)
        if character.current_location:
            nearby_npcs = nearby_npcs.filter(location=character.current_location)
        encounters = Encounter.objects.filter(session=session, is_resolved=False).order_by('id')
        return {
            'name': character.name,
            'role': character.role,
            'level': character.level,
            'hp': character.hp,
            'max_hp': character.max_hp,
            'coins': character.coins,
            'location': character.current_location,
            'status_effects': list(character.status_effects),
            'inventory': [{'item_name': i.item_name, 'quantity': i.quantity} for i in inventory],
            'quests': [{'title': q.title, 'status': q.status, 'reward_coins': q.reward_coins} for q in quests],
            'known_locations': list(session.world.locations or []),
            'nearby_npcs': [
                {'name': n.name, 'role': n.role, 'disposition': n.disposition} for n in nearby_npcs.order_by('name')[:10]
            ],
            'active_encounters': [{'kind': e.kind, 'title': e.title, 'difficulty': e.difficulty} for e in encounters],
        }

    def play_turn(self, *, session: StorySession, user_input: str) -> TurnResult:
        character = session.character
        world = session.world
        history = MongoService.get_conversation_history(session_id=session.id, limit=8)

        ai_output = self._ai.generate_story_turn(
            world_name=world.name,
            world_lore_summary=world.lore_summary,
            character_name=character.name,
            character_role=character.role,
            user_input=user_input,
            history=history,
            state=self.state_snapshot(character, session),
        )
        narrative = ai_output['narrative']
        events = EventRuleLayer.sanitize(ai_output.get('events', []))

        ctx = TurnContext(session=session, character=character, user_input=user_input, narrative=narrative)
        with transaction.atomic():
            applied = self._bus.publish(events, ctx)

        log_result = MongoService.insert_conversation_log(
            session_id=session.id,
            world_id=world.id,
            character_id=character.id,
            user_input=user_input,
            ai_output=narrative,
        )

        character.refresh_from_db()
        return TurnResult(
            narrative=narrative,
            events=applied,
            notes=ctx.notes,
            state=self.state_snapshot(character, session),
            history_saved=log_result.get('ok', False),
        )
