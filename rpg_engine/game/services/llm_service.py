"""Provider-agnostic LLM layer for the game.

`LLMService` owns every prompt and every piece of output parsing. A provider
subclass only has to say whether it is configured and how to turn one prompt
into raw text (`_complete`). Callers get an instance from `get_llm_service()`,
which picks the provider from settings:

    LLM_PROVIDER=anthropic   -> ClaudeService  (needs ANTHROPIC_API_KEY)
    LLM_PROVIDER=openai      -> OpenAIService  (needs OPENAI_API_KEY)
    LLM_PROVIDER unset       -> anthropic if ANTHROPIC_API_KEY is set, else openai
"""
from __future__ import annotations

import json
import os
import re

from django.conf import settings

from game.services import bible as BIBLE


class LLMService:
    provider: str = 'base'
    key_setting: str = ''

    # --- provider hooks ---------------------------------------------------

    @property
    def model(self) -> str:
        raise NotImplementedError

    def is_configured(self) -> bool:
        raise NotImplementedError

    def _complete(self, prompt: str, *, max_tokens: int) -> str:
        """Send one user prompt, return the model's raw text."""
        raise NotImplementedError

    # --- shared plumbing --------------------------------------------------

    def _ask(self, prompt: str, *, max_tokens: int) -> str:
        if not self.is_configured():
            raise ValueError(f'{self.key_setting} is not configured.')
        return (self._complete(prompt, max_tokens=max_tokens) or '').strip()

    def check(self) -> dict:
        if not self.is_configured():
            return {'ok': False, 'provider': self.provider, 'message': f'{self.key_setting} is not configured.'}
        try:
            text = self._ask('Reply with exactly: OK', max_tokens=32)
            return {'ok': True, 'provider': self.provider, 'message': f'Model reachable: {self.model}', 'sample': text}
        except Exception as exc:
            return {'ok': False, 'provider': self.provider, 'message': str(exc)}

    # --- game prompts -----------------------------------------------------

    def summarize_chapter(
        self,
        *,
        book_title: str,
        chapter_index: int,
        chapter_count: int,
        chapter_title: str,
        text: str,
        previous_summary: str = '',
    ) -> dict:
        """Structured digest of one chapter plus the hard evidence for the story bible.

        The returned dict is stored as the chapter's `summary`. Besides the prose fields it
        carries `bible` = normalize_chapter_bible(...): per-character quotes, reactions,
        relations and status (evidence only, no personality judgement), ordered plot beats
        and stated rules. See services/bible.py.
        """
        prompt = (
            'You are preparing a novel for adaptation into a text RPG. Read this chapter and fill the JSON template below '
            'for the game designer. Record only what the text supports; never invent. '
            f'Write prose fields in {settings.RPG_OUTPUT_LANGUAGE}; keep enum values exactly as given. Return strict JSON only:\n'
            '{\n'
            '  "summary": string, 120-200 words (150-300 characters if Chinese) covering the plot of this chapter,\n'
            '  "characters": [ for every named character who appears: {\n'
            '      "name": string (the name the narration uses most),\n'
            '      "aliases": [other names/titles used for this person in this chapter],\n'
            '      "identity": short phrase (who they are / role in the story),\n'
            '      "importance": "major" | "minor" (major = drives the plot in this chapter),\n'
            '      "status": short phrase, their situation at the END of this chapter (e.g. "dies", "captured", "allied with X"),\n'
            f'      "quotes": [0-{BIBLE.MAX_QUOTES_PER_CHAPTER} lines this character actually says, copied verbatim, each at most {BIBLE.MAX_QUOTE_CHARS} characters, '
            'preferably ones that show how they talk; empty if they do not speak],\n'
            f'      "reactions": [0-{BIBLE.MAX_REACTIONS_PER_CHAPTER} of {{"situation": what they faced, "action": what they actually did or said in response}}, '
            'e.g. stayed silent when questioned, laughed off a threat],\n'
            '      "relations": [0-4 of {"target": other character, "relation": short phrase}]\n'
            '  } ],\n'
            '  "locations": [place names visited or described],\n'
            '  "items": [notable objects, weapons, treasures, documents],\n'
            f'  "events": [3-{BIBLE.MAX_BEATS_PER_CHAPTER} key plot beats in order: {{"description": one sentence, '
            f'"type": one of {"|".join(BIBLE.BEAT_TYPES)}, "participants": [names], "consequence": short phrase or ""}}],\n'
            f'  "facts": [0-{BIBLE.MAX_FACTS_PER_CHAPTER} explicit rules or settings stated in this chapter (game rules, how the world works, '
            f'what an item does, who a faction is): {{"content": one sentence, "category": one of {"|".join(BIBLE.FACT_CATEGORIES)}}}],\n'
            '  "hooks": [2-4 open threads or quests a player could pursue here]\n'
            '}\n\n'
            f'Book: {book_title}\n'
            f'Chapter {chapter_index} of {chapter_count}: {chapter_title}\n'
            + (f'Previous chapter summary: {previous_summary}\n' if previous_summary else '')
            + f'\nChapter text:\n{text[:40000]}'
        )
        parsed = self._extract_json(self._ask(prompt, max_tokens=4000))
        return self.shape_chapter_summary(parsed, chapter_index=chapter_index)

    @staticmethod
    def shape_chapter_summary(parsed: dict, *, chapter_index: int) -> dict:
        """Model output -> stored summary. The prose fields keep their old shape; `bible` holds the evidence."""

        def strings(key: str) -> list[str]:
            value = parsed.get(key)
            return [str(v)[:200] for v in value if v][:20] if isinstance(value, list) else []

        bible = BIBLE.normalize_chapter_bible(parsed, chapter_index=chapter_index)
        return {
            'summary': str(parsed.get('summary', '')).strip(),
            'characters': [{'name': c['name'], 'role': c['identity'], 'status': c['status']} for c in bible['characters']],
            'locations': strings('locations'),
            'items': strings('items'),
            'events': [b['description'] for b in bible['beats']] or strings('events'),
            'hooks': strings('hooks'),
            'bible': bible,
        }

    def profile_character(self, *, book_title: str, character: dict) -> dict:
        """The one overall profile of a character, written from the whole book's collected evidence.

        Called once per major character after the scan (and again only when the evidence changes).
        """
        quotes = '\n'.join(f"- (ch{q['chapter']}) {q['text']}" for q in character.get('quotes', [])) or '(none recorded)'
        reactions = '\n'.join(
            f"- (ch{r['chapter']}) {r['situation']} -> {r['action']}" if r.get('situation') else f"- (ch{r['chapter']}) {r['action']}"
            for r in character.get('reactions', [])
        ) or '(none recorded)'
        timeline = '\n'.join(f"- (ch{t['chapter']}) {t['status']}" for t in character.get('timeline', [])) or '(none recorded)'
        relations = '; '.join(f"{r['target']}: {r['relation']}" for r in character.get('relations', [])) or '(none recorded)'
        prompt = (
            'You are writing the character bible for a text RPG adapted from a novel. Below is every piece of evidence '
            'collected about one character across the book: their actual lines, how they reacted to events, their status '
            'over time and their relations. Write ONE overall profile the narrator can use to keep this character in character. '
            'Base it only on the evidence; when the evidence shows they say little, say so. '
            f'Write prose in {settings.RPG_OUTPUT_LANGUAGE}. Return strict JSON only:\n'
            '{\n'
            '  "personality": 2-4 sentences on temperament, values and how they treat others,\n'
            '  "speech_style": 1-3 sentences on how they talk: length, tone, vocabulary, what they avoid saying, when they stay silent,\n'
            f'  "style_tags": pick the fitting side of each pair, omit a pair when unclear: {", ".join(f"{a}|{b}" for a, b in BIBLE.STYLE_TAG_PAIRS)},\n'
            '  "behaviour": [3-6 short rules of thumb for how they act, e.g. "answers a provocation with silence, not anger"]\n'
            '}\n\n'
            f'Book: {book_title}\n'
            f"Character: {character['name']}" + (f" (aka {', '.join(character['aliases'])})" if character.get('aliases') else '') + '\n'
            f"Identity: {character.get('identity', '')}\n"
            f"Appears in chapters: {', '.join(map(str, character.get('chapters', [])))}\n\n"
            f'Lines spoken:\n{quotes}\n\nReactions:\n{reactions}\n\nStatus over time:\n{timeline}\n\nRelations: {relations}\n'
        )
        parsed = self._extract_json(self._ask(prompt, max_tokens=1200))
        return BIBLE.normalize_profile(parsed, signature=BIBLE.evidence_signature(character))

    @staticmethod
    def chapter_digest(chapter_summaries: list[dict], *, max_chars: int = 60000) -> str:
        """Chapter summaries rendered as prompt text. Falls back to plot-only lines when too long."""
        if not chapter_summaries:
            return ''

        def render(ch: dict, *, full: bool) -> str:
            s = ch.get('summary') or {}
            lines = [f"Chapter {ch['index']} - {ch.get('title', '')}: {s.get('summary', '')}"]
            if full:
                if s.get('characters'):
                    lines.append('  Characters: ' + '; '.join(f"{c['name']} ({c['role']}; {c['status']})" for c in s['characters']))
                if s.get('locations'):
                    lines.append('  Locations: ' + ', '.join(s['locations']))
                if s.get('items'):
                    lines.append('  Items: ' + ', '.join(s['items']))
                if s.get('events'):
                    lines.append('  Events: ' + ' | '.join(s['events']))
                if s.get('hooks'):
                    lines.append('  Hooks: ' + ' | '.join(s['hooks']))
            return '\n'.join(lines)

        text = '\n'.join(render(ch, full=True) for ch in chapter_summaries)
        if len(text) > max_chars:
            text = '\n'.join(render(ch, full=False) for ch in chapter_summaries)
        return text[:max_chars]

    def generate_world(self, *, book_title: str, book_content: str, chapter_summaries: list[dict] | None = None) -> dict:
        digest = self.chapter_digest(chapter_summaries or [])
        source = (
            f'Chapter-by-chapter digest of the whole book:\n{digest}'
            if digest
            else f'Book excerpt:\n{book_content[:8000]}'
        )
        prompt = (
            'You are a game world designer. '
            'Based on the provided book content, generate a compact RPG world setup. '
            f'Write all fields in {settings.RPG_OUTPUT_LANGUAGE}. '
            'Return strict JSON only with keys: '
            'world_name (string), lore_summary (string, 150-250 words covering the whole arc of the book), '
            'factions (array of strings), '
            'locations (array of 6-12 strings, in the order the story visits them), main_conflict (string).\n\n'
            f'Book title: {book_title}\n\n'
            f'{source}'
        )
        parsed = self._extract_json(self._ask(prompt, max_tokens=1500))
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
        chapter_context: str = '',
        objective: str = '',
    ) -> dict:
        """Return {'narrative': str, 'events': list[dict], 'objective': str}.

        Events are raw model output; callers must pass them through
        EventRuleLayer before applying them to game state.
        """
        history = history or []
        history_text = '\n'.join(
            [f"Player: {item.get('user_input', '')}\nNarrator: {item.get('ai_output', '')}" for item in history]
        )
        state_text = json.dumps(state or {}, ensure_ascii=False)

        style = narrator_style()
        prompt = (
            'You are the narrator of a text RPG adapted from a novel; write this turn the way the novel\'s author would. '
            f'Write the narrative in {settings.RPG_OUTPUT_LANGUAGE}. '
            'Split the narrative into 2-4 short paragraphs separated by a blank line (\\n\\n inside the JSON string): '
            'start a new paragraph when the scene or viewpoint shifts and whenever a different character speaks. '
            + (f'\nWriting style rules (follow them strictly):\n{style}\n\n' if style else 'Keep it concise (about 80-160 words). ')
            + 'Return strict JSON only with keys:\n'
            '- narrative: string\n'
            '- objective: string, at most 40 characters, shown to the player as a hint of what they are currently '
            'trying to do, phrased as an ongoing attempt from the player\'s side ("we are trying to work out who the '
            'liar is", "we are trying to strike a deal with X"). Say what is being attempted, never how it turns out '
            'and nothing from later in the book. Keep the previous objective unless the situation has changed.\n'
            '- events: array of state changes caused by this turn. Allowed event objects:\n'
            '  {"type":"damage","amount":int,"source":str} {"type":"heal","amount":int}\n'
            '  {"type":"move","to":str} {"type":"gain_coins","amount":int} {"type":"lose_coins","amount":int}\n'
            '  {"type":"gain_item","item_name":str,"quantity":int} {"type":"lose_item","item_name":str,"quantity":int}\n'
            '  {"type":"add_status","status":str} {"type":"remove_status","status":str}\n'
            '  {"type":"quest_start","title":str,"description":str,"reward_coins":int}\n'
            '  {"type":"quest_complete","title":str} {"type":"quest_fail","title":str} {"type":"level_up"}\n'
            '  {"type":"spawn","kind":"npc","name":str,"role":str,"disposition":"friendly|neutral|hostile","location":str}\n'
            '  {"type":"spawn","kind":"encounter","encounter_kind":"combat|social|puzzle|discovery","title":str,"difficulty":1-5}\n'
            '  {"type":"spawn","kind":"location","name":str,"description":str,"danger_level":1-5}\n'
            '  {"type":"next_chapter"}\n'
            'Pacing and immersion rules:\n'
            '- The player is one participant among others. The other characters pursue their own goals and keep '
            'talking and acting; they do NOT all stop and wait for the player. Only address the player directly when '
            'it is natural for that character (a host calling the next person, a suspicious character pressing them, '
            'a friend asking what they think), at most one such address per turn, and not every turn.\n'
            '- Vary how a turn ends. Rotate between: (a) something aimed at the player that demands a reaction, '
            'described from their point of view (a harpoon flies toward you, a hand grabs your wrist, the table turns '
            'under your palm); (b) a question or look from one character; (c) a quiet moment where the player is free '
            'to act while others are busy. Never end two turns in a row the same way.\n'
            '- When the player enters a new place or the scene changes, spend the first paragraph on what they '
            'perceive: layout, light, sounds, smells, who is where, what is within reach. Give them things to '
            'interact with, then let them choose.\n'
            '- Something happens every turn: new information, an action, a change in the situation. Advance one or two '
            'beats per turn (a whole speech may finish within a turn); do not jump across several scenes, and never '
            'stall with description alone when the player says "continue" or "wait".\n'
            '- React to what the player actually said or did; the other characters remember it. If the player only '
            'watches, the plot still moves on around them.\n'
            '- Background characters are people, not fixtures. Do not list what everyone is doing every turn: focus on '
            'the player and the one or two people they are dealing with. Every few turns, in one sentence, show the '
            'room or someone else doing something new and specific (arguing in a corner, testing the wall, pouring '
            'water, dozing off). Never reuse a gesture or detail that already appears in the history, such as the same '
            'character tapping the table again.\n'
            'Only emit events that actually happen in the narrative. Use an empty array if nothing changes. '
            'Use spawn when a new character, place or encounter is introduced for the first time. '
            'Only move to locations that exist in the world. Only complete quests that are active. '
            'Emit next_chapter when the player has played through the main beats of the current chapter '
            'and the story should move on to the next one.\n\n'
            f'World: {world_name}\n'
            f'Lore: {world_lore_summary}\n'
            + (
                'Source book context (follow its plot and characters, adapting to the player\'s choices). '
                'Where a character bible is given it is the ground truth for how that person speaks and acts: match their '
                'recorded lines and reactions, keep their replies as short as their style says, and let them stay silent or '
                'deflect when that is what they would do. Never reveal events from later chapters.\n'
                f'{chapter_context}\n'
                if chapter_context else ''
            )
            + f'Character: {character_name}\n'
            f'Role: {character_role or "Adventurer"}\n'
            f'Current state: {state_text}\n'
            + (f'Current objective shown to the player: {objective}\n' if objective else '')
            + '\n'
            f'History:\n{history_text if history_text else "(none)"}\n\n'
            f'Current player action: {user_input}\n'
        )

        text = self._ask(prompt, max_tokens=1200)
        if not text:
            raise ValueError(f'{self.provider} returned empty story output.')

        try:
            parsed = self._extract_json(text)
        except ValueError:
            # Model ignored the JSON instruction. One retry with the reminder; if that fails too,
            # keep the readable prose only (no stray fences or self-talk) and apply no state changes.
            try:
                parsed = self._extract_json(self._ask(prompt + '\nReply with the JSON object only, nothing else.', max_tokens=1200))
            except ValueError:
                return {'narrative': self._prose_only(text), 'events': [], 'objective': objective}

        narrative = str(parsed.get('narrative', '')).strip() or self._prose_only(text)
        events = parsed.get('events')
        new_objective = str(parsed.get('objective') or '').strip()[:120] or objective
        return {'narrative': narrative, 'events': events if isinstance(events, list) else [], 'objective': new_objective}

    @staticmethod
    def _prose_only(text: str) -> str:
        """Strip code fences, tags and meta remarks a model sometimes appends to a non-JSON reply."""
        text = text.split('```')[0]
        text = re.sub(r'<[^>\n]{1,80}>', '', text)
        kept = [
            line for line in text.splitlines()
            if not re.match(r'^\s*(wait\b|note\b|i must\b|i need to\b|as an ai\b|i should\b)', line.strip(), re.IGNORECASE)
        ]
        return '\n'.join(kept).strip() or text.strip()

    def generate_market_candidates(
        self,
        *,
        world_name: str,
        world_lore_summary: str,
        book_title: str,
        book_content: str,
        chapter_summaries: list[dict] | None = None,
    ) -> dict:
        digest = self.chapter_digest(chapter_summaries or [], max_chars=20000)
        source = f'Chapter digest:\n{digest}' if digest else f'Book excerpt: {book_content[:5000]}'
        prompt = (
            "Generate RPG market candidates based on the book/world. Return strict JSON only with keys:\n"
            "- items: array of {name, category, rarity(common|rare|epic), base_price(number), stock(number)}\n"
            "- merchants: array of {name, location, price_multiplier(number), buyback_rate(number)}\n"
            f"Language: {settings.RPG_OUTPUT_LANGUAGE}\n\n"
            f"World: {world_name}\n"
            f"Lore: {world_lore_summary}\n"
            f"Book title: {book_title}\n"
            f"{source}"
        )
        parsed = self._extract_json(self._ask(prompt, max_tokens=1500))
        parsed.setdefault('items', [])
        parsed.setdefault('merchants', [])
        return parsed

    def generate_components(
        self,
        *,
        kind: str,
        schema: str,
        world_name: str,
        world_lore_summary: str,
        known_locations: list[str],
        count: int,
        hint: str = '',
    ) -> list[dict]:
        """Ask the model for `count` component specs of `kind`; returns raw dicts."""
        prompt = (
            f'You are a game content designer. Generate exactly {count} new {kind}(s) that fit this world. '
            f'Write text fields in {settings.RPG_OUTPUT_LANGUAGE}. '
            f'Return strict JSON only: an array where each element is {schema}. '
            'Prefer locations from the known list when a location field is present.\n\n'
            f'World: {world_name}\n'
            f'Lore: {world_lore_summary}\n'
            f'Known locations: {", ".join(known_locations) or "(none)"}\n'
            f'Designer hint: {hint or "(none)"}\n'
        )
        return self._extract_json_array(self._ask(prompt, max_tokens=1500))

    def parse_trade_intent(self, *, user_input: str, allowed_items: list[str]) -> dict:
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
        data = self._extract_json(self._ask(prompt, max_tokens=200))
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

    # --- parsing ----------------------------------------------------------

    @staticmethod
    def _json_values(text: str) -> list:
        """Every top-level JSON object/array embedded in `text`, in order.

        Models sometimes wrap JSON in fences or prose, or send a second
        "corrected" object after the first; a greedy regex would glue those
        together, so decode value by value instead.
        """
        decoder = json.JSONDecoder()
        values, pos = [], 0
        while True:
            starts = [i for i in (text.find('{', pos), text.find('[', pos)) if i != -1]
            if not starts:
                return values
            start = min(starts)
            try:
                value, pos = decoder.raw_decode(text, start)
                values.append(value)
            except json.JSONDecodeError:
                pos = start + 1

    @classmethod
    def _extract_json_array(cls, text: str) -> list[dict]:
        if not text:
            raise ValueError('Model returned empty response.')
        for data in reversed(cls._json_values(text)):
            if isinstance(data, dict):
                # Tolerate {"items": [...]}-style envelopes.
                lists = [v for v in data.values() if isinstance(v, list)]
                data = lists[0] if lists else [data]
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        raise ValueError('Failed to parse JSON array from model output.')

    @classmethod
    def _extract_json(cls, text: str) -> dict:
        """The last JSON object in `text` (a model's correction wins over its first try)."""
        if not text:
            raise ValueError('Model returned empty response.')
        for data in reversed(cls._json_values(text)):
            if isinstance(data, dict):
                return data
        raise ValueError('Failed to parse JSON from model output.')


_style_cache: dict = {'path': None, 'mtime': None, 'text': ''}


def narrator_style() -> str:
    """Contents of settings.NARRATOR_STYLE_FILE, re-read whenever the file changes."""
    path = getattr(settings, 'NARRATOR_STYLE_FILE', '')
    if not path:
        return ''
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ''
    if _style_cache['path'] != path or _style_cache['mtime'] != mtime:
        with open(path, encoding='utf-8') as fh:
            _style_cache.update(path=path, mtime=mtime, text=fh.read().strip()[:6000])
    return _style_cache['text']


def get_llm_service(provider: str | None = None) -> LLMService:
    """Return the configured provider (see module docstring)."""
    name = (provider or getattr(settings, 'LLM_PROVIDER', '') or '').strip().lower()
    if not name:
        name = 'anthropic' if getattr(settings, 'ANTHROPIC_API_KEY', '') else 'openai'
    if name in {'anthropic', 'claude'}:
        from game.services.claude_service import ClaudeService

        return ClaudeService()
    if name == 'openai':
        from game.services.openai_service import OpenAIService

        return OpenAIService()
    raise ValueError(f'Unknown LLM_PROVIDER: {name!r} (use anthropic or openai)')
