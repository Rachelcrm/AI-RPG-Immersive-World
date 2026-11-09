from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from game.models import Character, Encounter, InventoryItem, NPC, Quest, StorySession
from game.services.events import EventRuleLayer, GameEvent, GameStateBus, TurnContext, build_default_bus, note
from game.services.bible import narrator_context
from game.services.mongo_service import MongoService
from game.services.llm_service import LLMService, get_llm_service


@dataclass
class TurnResult:
    narrative: str
    events: list[GameEvent]
    notes: list[str]
    state: dict
    history_saved: bool
    session_status: str = 'active'
    objective: str = ''


class StoryService:
    """One game turn: narrate, sanitize events, publish to observers, snapshot state."""

    def __init__(self, *, bus: GameStateBus | None = None, ai: LLMService | None = None) -> None:
        self._bus = bus or build_default_bus()
        self._ai = ai or get_llm_service()

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
            'coins': str(character.coins),
            'location': character.current_location,
            'status_effects': list(character.status_effects),
            'inventory': [{'item_name': i.item_name, 'quantity': i.quantity} for i in inventory],
            'quests': [{'title': q.title, 'status': q.status, 'reward_coins': q.reward_coins} for q in quests],
            'known_locations': list(session.world.locations or []),
            'chapter': session.current_chapter,
            'chapter_count': session.world.book.chapter_count if session.world.book_id else 0,
            'nearby_npcs': [
                {'name': n.name, 'role': n.role, 'disposition': n.disposition} for n in nearby_npcs.order_by('name')[:10]
            ],
            'active_encounters': [{'kind': e.kind, 'title': e.title, 'difficulty': e.difficulty} for e in encounters],
        }

    @staticmethod
    def chapter_context(session: StorySession) -> str:
        """World bible, the summaries of the current chapter and its neighbours, and the story bible for this chapter."""
        world = session.world
        lines = []
        if world.factions:
            lines.append('Factions: ' + ', '.join(map(str, world.factions)))
        if world.main_conflict:
            lines.append(f'Main conflict: {world.main_conflict}')
        if world.book_id and world.book.chapter_count:
            current = session.current_chapter
            wanted = [i for i in (current - 1, current, current + 1) if 1 <= i <= world.book.chapter_count]
            summaries = MongoService.get_chapter_summaries(book_id=world.book.store_key, indexes=wanted)
            if summaries:
                lines.append(f'The story is currently in chapter {current} of {world.book.chapter_count}.')
                lines.append(LLMService.chapter_digest(summaries, max_chars=12000))
            present = [
                c['name']
                for ch in summaries
                if ch['index'] == current
                for c in (ch.get('summary') or {}).get('characters', [])
            ]
            if session.character.current_location:
                present += list(
                    NPC.objects.filter(world=world, is_alive=True, location=session.character.current_location)
                    .values_list('name', flat=True)
                )
            bible = narrator_context(
                characters=MongoService.get_characters(book_id=world.book.store_key),
                plot=MongoService.get_plot(book_id=world.book.store_key, chapter=current),
                facts=MongoService.get_facts(book_id=world.book.store_key),
                chapter=current,
                present=present,
            )
            if bible:
                lines.append(bible)
        return '\n'.join(lines)

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
            chapter_context=self.chapter_context(session),
            objective=session.objective,
        )
        narrative = ai_output['narrative']
        objective = str(ai_output.get('objective') or session.objective)[:120]
        if objective != session.objective:
            session.objective = objective
            session.save(update_fields=['objective', 'updated_at'])
        events = EventRuleLayer.sanitize(ai_output.get('events', []))

        ctx = TurnContext(session=session, character=character, user_input=user_input, narrative=narrative)
        with transaction.atomic():
            applied = self._bus.publish(events, ctx)
            if not character.is_alive:
                session.status = StorySession.STATUS_ENDED
                session.save(update_fields=['status', 'updated_at'])
                ctx.notes.append(note('story_end'))

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
            session_status=session.status,
            objective=objective,
        )
