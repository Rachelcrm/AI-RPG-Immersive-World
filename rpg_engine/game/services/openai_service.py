import json
import re

from django.conf import settings
from openai import OpenAI


class OpenAIService:
    def __init__(self) -> None:
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None

    def check(self) -> dict:
        if not self._client:
            return {'ok': False, 'message': 'OPENAI_API_KEY is not configured.'}
        try:
            response = self._client.responses.create(
                model=settings.OPENAI_MODEL,
                input='Reply with exactly: OK',
                max_output_tokens=32,
            )
            text = (response.output_text or '').strip()
            return {'ok': True, 'message': f'Model reachable: {settings.OPENAI_MODEL}', 'sample': text}
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}

    def generate_world(self, *, book_title: str, book_content: str) -> dict:
        if not self._client:
            raise ValueError('OPENAI_API_KEY is not configured.')

        prompt = (
            'You are a game world designer. '\
            'Based on the provided book content, generate a compact RPG world setup. '\
            f'Write all fields in {settings.RPG_OUTPUT_LANGUAGE}. '\
            'Return strict JSON only with keys: '\
            'world_name (string), lore_summary (string), factions (array of strings), '\
            'locations (array of strings), main_conflict (string).\n\n'
            f'Book title: {book_title}\n\n'
            f'Book excerpt:\n{book_content[:8000]}'
        )

        response = self._client.responses.create(
            model=settings.OPENAI_MODEL,
            input=prompt,
            max_output_tokens=700,
        )
        raw_text = (response.output_text or '').strip()
        parsed = self._extract_json(raw_text)

        return {
            'world_name': str(parsed.get('world_name', 'Untitled World')),
            'lore_summary': str(parsed.get('lore_summary', '')),
            'factions': parsed.get('factions') if isinstance(parsed.get('factions'), list) else [],
            'locations': parsed.get('locations') if isinstance(parsed.get('locations'), list) else [],
            'main_conflict': str(parsed.get('main_conflict', '')),
        }

    def generate_story_turn(
        self,
        *,
        world_name: str,
        world_lore_summary: str,
        character_name: str,
        character_role: str,
        user_input: str,
        history: list[dict] | None = None,
        state: dict | None = None,
    ) -> dict:
        """Return {'narrative': str, 'events': list[dict]}.

        Events are raw model output; callers must pass them through
        EventRuleLayer before applying them to game state.
        """
        if not self._client:
            raise ValueError('OPENAI_API_KEY is not configured.')

        history = history or []
        history_text = '\n'.join(
            [f"Player: {item.get('user_input', '')}\nNarrator: {item.get('ai_output', '')}" for item in history]
        )
        state_text = json.dumps(state or {}, ensure_ascii=False)

        prompt = (
            'You are the narrative engine for a text RPG. '
            'Continue the story in an immersive style and keep it concise (about 60-120 words). '
            f'Write the narrative in {settings.RPG_OUTPUT_LANGUAGE}. '
            'Return strict JSON only with keys:\n'
            '- narrative: string\n'
            '- events: array of state changes caused by this turn. Allowed event objects:\n'
            '  {"type":"damage","amount":int,"source":str} {"type":"heal","amount":int}\n'
            '  {"type":"move","to":str} {"type":"gain_coins","amount":int} {"type":"lose_coins","amount":int}\n'
            '  {"type":"gain_item","item_name":str,"quantity":int} {"type":"lose_item","item_name":str,"quantity":int}\n'
            '  {"type":"add_status","status":str} {"type":"remove_status","status":str}\n'
            '  {"type":"quest_start","title":str,"description":str,"reward_coins":int}\n'
            '  {"type":"quest_complete","title":str} {"type":"quest_fail","title":str} {"type":"level_up"}\n'
            'Only emit events that actually happen in the narrative. Use an empty array if nothing changes. '
            'Only move to locations that exist in the world. Only complete quests that are active.\n\n'
            f'World: {world_name}\n'
            f'Lore: {world_lore_summary}\n'
            f'Character: {character_name}\n'
            f'Role: {character_role or "Adventurer"}\n'
            f'Current state: {state_text}\n\n'
            f'History:\n{history_text if history_text else "(none)"}\n\n'
            f'Current player action: {user_input}\n'
        )

        response = self._client.responses.create(
            model=settings.OPENAI_MODEL,
            input=prompt,
            max_output_tokens=500,
        )
        text = (response.output_text or '').strip()
        if not text:
            raise ValueError('OpenAI returned empty story output.')

        try:
            parsed = self._extract_json(text)
        except ValueError:
            # Model ignored the JSON instruction; keep the prose, apply no state changes.
            return {'narrative': text, 'events': []}

        narrative = str(parsed.get('narrative', '')).strip() or text
        events = parsed.get('events')
        return {'narrative': narrative, 'events': events if isinstance(events, list) else []}

    def generate_market_candidates(
        self,
        *,
        world_name: str,
        world_lore_summary: str,
        book_title: str,
        book_content: str,
    ) -> dict:
        if not self._client:
            raise ValueError('OPENAI_API_KEY is not configured.')

        prompt = (
            "Generate RPG market candidates based on the book/world. Return strict JSON only with keys:\n"
            "- items: array of {name, category, rarity(common|rare|epic), base_price(number), stock(number)}\n"
            "- merchants: array of {name, location, price_multiplier(number), buyback_rate(number)}\n"
            f"Language: {settings.RPG_OUTPUT_LANGUAGE}\n\n"
            f"World: {world_name}\n"
            f"Lore: {world_lore_summary}\n"
            f"Book title: {book_title}\n"
            f"Book excerpt: {book_content[:5000]}"
        )
        response = self._client.responses.create(
            model=settings.OPENAI_MODEL,
            input=prompt,
            max_output_tokens=900,
        )
        parsed = self._extract_json((response.output_text or '').strip())
        if 'items' not in parsed:
            parsed['items'] = []
        if 'merchants' not in parsed:
            parsed['merchants'] = []
        return parsed

    def parse_trade_intent(self, *, user_input: str, allowed_items: list[str]) -> dict:
        if not self._client:
            raise ValueError('OPENAI_API_KEY is not configured.')
        items_text = ', '.join(allowed_items[:200])
        prompt = (
            "Parse the trade intent from user text. Return strict JSON only with keys:\n"
            "- action: buy|sell\n"
            "- item_name: string (must be from allowed items, best match)\n"
            "- quantity: integer >= 1\n"
            "- strategy: fixed|negotiation|barter\n\n"
            f"Allowed items: {items_text}\n"
            f"User input: {user_input}\n"
        )
        response = self._client.responses.create(
            model=settings.OPENAI_MODEL,
            input=prompt,
            max_output_tokens=200,
        )
        data = self._extract_json((response.output_text or '').strip())
        action = str(data.get('action', 'buy')).lower()
        if action not in {'buy', 'sell'}:
            action = 'buy'
        strategy = str(data.get('strategy', 'fixed')).lower()
        if strategy not in {'fixed', 'negotiation', 'barter'}:
            strategy = 'fixed'
        quantity = int(data.get('quantity', 1) or 1)
        if quantity < 1:
            quantity = 1
        item_name = str(data.get('item_name', '')).strip()
        if not item_name:
            raise ValueError('Failed to identify item_name from trade intent.')
        return {'action': action, 'item_name': item_name, 'quantity': quantity, 'strategy': strategy}

    @staticmethod
    def _extract_json(text: str) -> dict:
        if not text:
            raise ValueError('OpenAI returned empty response.')

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        match = re.search(r'\{[\s\S]*\}', text)
        if not match:
            raise ValueError('Failed to parse JSON from model output.')

        data = json.loads(match.group(0))
        if not isinstance(data, dict):
            raise ValueError('Model output JSON is not an object.')
        return data
