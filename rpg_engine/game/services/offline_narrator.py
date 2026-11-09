"""Deterministic stand-in for the LLM services when no API key is configured.

It implements the same generate_* methods the game loop calls, so the
full turn pipeline (events -> observers -> snapshot) runs unchanged.
Useful for demos, tests, and developing without network access.
"""
from __future__ import annotations

import random
import re

from game.services.bible import evidence_signature, normalize_profile
from game.services.llm_service import LLMService


class OfflineNarrator:
    _LOOT = ['Torch', 'Rope', 'Dried Meat', 'Old Coin', 'Iron Nail']

    def __init__(self, seed: int | None = 7) -> None:
        self._rng = random.Random(seed)

    def check(self) -> dict:
        return {'ok': True, 'message': 'offline narrator'}

    def generate_world(self, *, book_title: str, book_content: str, chapter_summaries: list[dict] | None = None) -> dict:
        # Capitalized multi-word phrases make serviceable place names.
        phrases = re.findall(r'\b(?:[A-Z][a-z]+ ){1,2}[A-Z][a-z]+\b', book_content)
        seen: list[str] = []
        for phrase in phrases:
            if phrase not in seen:
                seen.append(phrase)
        locations = seen[:4] or ['Starting Camp', 'Old Road', 'Ruined Keep']
        return {
            'world_name': f'World of {book_title}',
            'lore_summary': book_content[:200].strip(),
            'factions': ['Wanderers', 'Watchers'],
            'locations': locations,
            'main_conflict': 'Unknown forces stir in the land.',
        }

    def summarize_chapter(self, *, chapter_index: int, chapter_title: str, text: str, **_) -> dict:
        phrases = re.findall(r'\b(?:[A-Z][a-z]+ ){1,2}[A-Z][a-z]+\b', text)
        names: list[str] = []
        for phrase in phrases:
            if phrase not in names:
                names.append(phrase)
        spoken = re.findall(r'[“"]([^”"]{3,60})[”"]', text)
        raw = {
            'summary': ' '.join(text.split())[:300],
            'characters': [
                {
                    'name': n,
                    'identity': 'figure',
                    'importance': 'major' if i == 0 else 'minor',
                    'status': 'present',
                    'quotes': spoken[:2] if i == 0 else [],
                    'reactions': [{'situation': 'asked a question', 'action': 'answers briefly'}] if i == 0 else [],
                    'relations': [{'target': names[1], 'relation': 'companion'}] if i == 0 and len(names) > 1 else [],
                }
                for i, n in enumerate(names[:3])
            ],
            'locations': names[3:6],
            'items': [],
            'events': [{'description': f'Chapter {chapter_index} ({chapter_title}) unfolds.', 'type': 'other', 'participants': names[:1]}],
            'facts': [{'content': f'Chapter {chapter_index} has a title: {chapter_title}.', 'category': 'world'}] if chapter_title else [],
            'hooks': ['Find out what happens next.'],
        }
        return LLMService.shape_chapter_summary(raw, chapter_index=chapter_index)

    def profile_character(self, *, book_title: str, character: dict) -> dict:
        raw = {
            'personality': f"{character['name']} is steady and watchful.",
            'speech_style': 'Speaks briefly and plainly.',
            'style_tags': ['terse', 'calm'],
            'behaviour': ['keeps own counsel until asked twice'],
        }
        return normalize_profile(raw, signature=evidence_signature(character))

    def generate_components(self, *, kind: str, count: int, known_locations: list[str], **_) -> list[dict]:
        names = ['Garr', 'Mira', 'Old Pell', 'Sable', 'Tomas', 'Wren']
        self._rng.shuffle(names)
        if kind == 'npc':
            return [
                {
                    'name': names[i % len(names)],
                    'role': self._rng.choice(['Guard', 'Trader', 'Hermit', 'Scout']),
                    'location': self._rng.choice(known_locations) if known_locations else '',
                    'disposition': self._rng.choice(['friendly', 'neutral', 'hostile']),
                }
                for i in range(count)
            ]
        if kind == 'location':
            return [{'name': f'Hidden Path {i + 1}', 'danger_level': self._rng.randint(1, 4)} for i in range(count)]
        if kind == 'item':
            return [{'name': n, 'category': 'misc', 'rarity': 'common', 'base_price': 5} for n in self._LOOT[:count]]
        return [{'title': 'Strange noise', 'kind': 'discovery', 'difficulty': 1} for _ in range(count)]

    def generate_market_candidates(self, **_) -> dict:
        return {
            'items': [
                {'name': 'Traveler Ration', 'category': 'food', 'rarity': 'common', 'base_price': 4, 'stock': 10},
                {'name': 'Torch', 'category': 'tool', 'rarity': 'common', 'base_price': 3, 'stock': 6},
                {'name': 'Moon Shard', 'category': 'relic', 'rarity': 'rare', 'base_price': 40, 'stock': 1},
            ],
            'merchants': [{'name': 'Old Pell', 'location': '', 'price_multiplier': 1.0, 'buyback_rate': 0.6}],
        }

    def parse_trade_intent(self, **_) -> dict:
        raise ValueError('offline narrator has no intent parser; use rule fallback')

    def generate_story_turn(self, *, user_input: str, state: dict | None = None, objective: str = '', **_) -> dict:
        """Tiny command grammar so the demo loop produces real state changes."""
        state = state or {}
        text = user_input.strip().lower()
        known = state.get('known_locations') or []
        events: list[dict] = []

        move = re.match(r'(?:go|walk|travel|head)(?: to)?\s+(.+)', text)
        if move:
            target = next((loc for loc in known if loc.lower() == move.group(1).strip()), None)
            if target:
                events.append({'type': 'move', 'to': target})
                narrative = f'You make your way to {target}. The air feels different here.'
            else:
                narrative = f"You look for a path to '{move.group(1)}' but find none you know."
        elif text.startswith('rest'):
            events.append({'type': 'heal', 'amount': 20})
            narrative = 'You rest by a small fire and feel your strength return.'
        elif text.startswith(('search', 'look', 'explore')):
            loot = self._rng.choice(self._LOOT)
            events.append({'type': 'gain_item', 'item_name': loot, 'quantity': 1})
            if self._rng.random() < 0.3:
                events.append({'type': 'spawn', 'kind': 'encounter', 'encounter_kind': 'combat', 'title': 'Lurking shadow', 'difficulty': 2})
            narrative = f'You search the area carefully and find a {loot}.'
        elif text.startswith(('fight', 'attack')):
            dmg = self._rng.randint(5, 25)
            events.append({'type': 'damage', 'amount': dmg, 'source': 'the enemy'})
            events.append({'type': 'gain_coins', 'amount': self._rng.randint(3, 12)})
            narrative = f'Steel rings out. You win, but not unscathed: you take {dmg} damage and loot a few coins.'
        elif text.startswith('talk'):
            npcs = state.get('nearby_npcs') or []
            if npcs:
                npc = npcs[0]
                events.append({'type': 'quest_start', 'title': f"{npc['name']}'s errand", 'description': 'A small favor.', 'reward_coins': 15})
                narrative = f"{npc['name']} the {npc['role']} eyes you warily, then asks for a small favor."
            else:
                narrative = 'There is no one here to talk to.'
        elif text.startswith(('finish', 'complete')):
            active = [q for q in state.get('quests', []) if q['status'] == 'active']
            if active:
                events.append({'type': 'quest_complete', 'title': active[0]['title']})
                narrative = f"You report back. '{active[0]['title']}' is done."
            else:
                narrative = 'You have no open errands.'
        else:
            narrative = f'You {user_input.strip()}. Nothing much comes of it.'

        return {'narrative': narrative, 'events': events, 'objective': objective}
