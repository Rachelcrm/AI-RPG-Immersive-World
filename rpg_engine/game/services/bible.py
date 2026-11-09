"""The story bible: hard, code-owned facts extracted from a book, kept apart from the prose summaries.

Three kinds of records, all per book:

    characters  one document per character: identity, aliases, where they appear, verbatim
                quotes, observed reactions, relations and status changes (all with chapter
                numbers) plus ONE overall profile (personality, speech style, style tags)
                written once from the whole book's evidence
    plot        one document per key beat: chapter, order, type, participants, consequence
    facts       one document per world/game rule, with the chapter that introduces it

The chapter scan (`LLMService.summarize_chapter`) only collects evidence; it never judges
personality. `normalize_chapter_bible` forces that evidence into the fixed schema below,
`merge_bible` folds every chapter's evidence into the per-book records without any model
call, and `LLMService.profile_character` later writes the single overall profile per major
character. The narrator receives `narrator_context`: nothing from chapters the player has
not reached yet.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from django.conf import settings

# Closed vocabularies. The model may only pick from these; anything else is dropped.
STYLE_TAG_PAIRS: list[tuple[str, str]] = [
    ('terse', 'talkative'),
    ('blunt', 'indirect'),
    ('formal', 'casual'),
    ('calm', 'emotional'),
    ('humorous', 'serious'),
    ('polite', 'harsh'),
    ('confident', 'hesitant'),
]
STYLE_TAGS: set[str] = {tag for pair in STYLE_TAG_PAIRS for tag in pair}
STYLE_TAG_LABELS_ZH = {
    'terse': '话少', 'talkative': '话多', 'blunt': '直接', 'indirect': '含蓄', 'formal': '书面', 'casual': '口语',
    'calm': '冷静', 'emotional': '情绪化', 'humorous': '幽默', 'serious': '严肃', 'polite': '客气', 'harsh': '刻薄',
    'confident': '笃定', 'hesitant': '犹豫',
}
BEAT_TYPES = ('reveal', 'death', 'game', 'decision', 'relationship', 'conflict', 'other')
FACT_CATEGORIES = ('rule', 'world', 'item', 'faction')
IMPORTANCE = ('major', 'minor')

MAX_QUOTE_CHARS = 60
MAX_QUOTES_PER_CHAPTER = 4
MAX_REACTIONS_PER_CHAPTER = 3
MAX_CHARACTERS_PER_CHAPTER = 15
MAX_BEATS_PER_CHAPTER = 8
MAX_FACTS_PER_CHAPTER = 8
MAX_QUOTES = 40  # kept per character after merging
MAX_REACTIONS = 30
MAJOR_MIN_CHAPTERS = 3  # appearing in this many units makes a character major even if never flagged


def _text(value, limit: int) -> str:
    return re.sub(r'\s+', ' ', str(value if value is not None else '')).strip()[:limit]


def _strings(value, *, limit: int, count: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for v in value:
        t = _text(v, limit)
        if t and t not in out:
            out.append(t)
    return out[:count]


def _key(name: str) -> str:
    """Name normalised for matching: case/space/punctuation-insensitive."""
    return re.sub(r'[\s\W_]+', '', str(name)).lower()


# --- per-chapter evidence ---------------------------------------------------------


def normalize_chapter_bible(raw: dict, *, chapter_index: int) -> dict:
    """Force one chapter's model output into the evidence schema. Unknown fields and enum values are dropped.

    Returns {'characters': [...], 'beats': [...], 'facts': [...]} where
      character = {name, aliases, identity, importance, status, quotes, reactions, relations}
      beat      = {chapter, order, description, type, participants, consequence}
      fact      = {chapter, content, category}
    """
    characters = []
    for item in raw.get('characters') or []:
        if isinstance(item, str):
            item = {'name': item}
        if not isinstance(item, dict):
            continue
        name = _text(item.get('name'), 120)
        if not name:
            continue
        importance = _text(item.get('importance'), 10).lower()
        quotes = []
        for q in item.get('quotes') or []:
            t = _text(q, MAX_QUOTE_CHARS).strip('“”"\'「」')
            if t and t not in quotes:
                quotes.append(t)
        reactions = []
        for r in item.get('reactions') or []:
            if isinstance(r, dict):
                situation, action = _text(r.get('situation'), 120), _text(r.get('action'), 160)
            else:
                situation, action = '', _text(r, 160)
            if action:
                reactions.append({'situation': situation, 'action': action})
        relations = []
        for r in item.get('relations') or []:
            if isinstance(r, dict):
                target, relation = _text(r.get('target'), 120), _text(r.get('relation'), 120)
                if target and relation:
                    relations.append({'target': target, 'relation': relation})
        characters.append(
            {
                'name': name,
                'aliases': [a for a in _strings(item.get('aliases'), limit=60, count=6) if _key(a) != _key(name)],
                'identity': _text(item.get('identity') or item.get('role'), 160),
                'importance': importance if importance in IMPORTANCE else 'minor',
                'status': _text(item.get('status'), 200),
                'quotes': quotes[:MAX_QUOTES_PER_CHAPTER],
                'reactions': reactions[:MAX_REACTIONS_PER_CHAPTER],
                'relations': relations[:6],
            }
        )

    beats = []
    for item in raw.get('events') or raw.get('beats') or []:
        if isinstance(item, str):
            item = {'description': item}
        if not isinstance(item, dict):
            continue
        description = _text(item.get('description') or item.get('event'), 300)
        if not description:
            continue
        kind = _text(item.get('type'), 20).lower()
        beats.append(
            {
                'chapter': chapter_index,
                'order': len(beats) + 1,
                'description': description,
                'type': kind if kind in BEAT_TYPES else 'other',
                'participants': _strings(item.get('participants'), limit=120, count=8),
                'consequence': _text(item.get('consequence'), 300),
            }
        )

    facts = []
    for item in raw.get('facts') or []:
        if isinstance(item, str):
            item = {'content': item}
        if not isinstance(item, dict):
            continue
        content = _text(item.get('content') or item.get('rule'), 300)
        if not content:
            continue
        category = _text(item.get('category'), 20).lower()
        facts.append({'chapter': chapter_index, 'content': content, 'category': category if category in FACT_CATEGORIES else 'world'})

    return {
        'characters': characters[:MAX_CHARACTERS_PER_CHAPTER],
        'beats': beats[:MAX_BEATS_PER_CHAPTER],
        'facts': facts[:MAX_FACTS_PER_CHAPTER],
    }


# --- merging across chapters (no model) -------------------------------------------


def merge_bible(chapter_summaries: list[dict]) -> dict:
    """Fold every chapter's evidence into per-book records.

    `chapter_summaries` is what MongoService.get_chapter_summaries returns; a chapter whose
    summary carries no 'bible' key contributes nothing. Returns {'characters', 'plot', 'facts'}.
    Characters are matched by normalised name and by alias; the earliest-seen name is canonical.
    """
    canonical: dict[str, str] = {}  # key(name or alias) -> canonical key
    records: dict[str, dict] = {}

    def resolve(name: str) -> str:
        k = _key(name)
        while k in canonical and canonical[k] != k:
            k = canonical[k]
        return k

    def ensure(name: str) -> dict:
        k = resolve(name)
        if k not in records:
            canonical[k] = k
            records[k] = {
                'name': name,
                'aliases': [],
                'identities': Counter(),
                'importance_votes': Counter(),
                'chapters': set(),
                'quotes': [],
                'reactions': [],
                'relations': {},
                'timeline': [],
            }
        return records[k]

    def link_alias(alias: str, rec_key: str) -> None:
        a = resolve(alias)
        if a == rec_key:
            return
        if a in records:  # alias was first met as a character of its own: merge it in
            other = records.pop(a)
            rec = records[rec_key]
            rec['aliases'] = [x for x in [other['name'], *other['aliases']] if _key(x) != rec_key and x not in rec['aliases']] + rec['aliases']
            rec['identities'] += other['identities']
            rec['importance_votes'] += other['importance_votes']
            rec['chapters'] |= other['chapters']
            rec['quotes'] += other['quotes']
            rec['reactions'] += other['reactions']
            rec['relations'].update({k: v for k, v in other['relations'].items() if k not in rec['relations']})
            rec['timeline'] += other['timeline']
        canonical[a] = rec_key

    plot: list[dict] = []
    facts: list[dict] = []
    seen_facts: set[str] = set()

    for ch in sorted(chapter_summaries, key=lambda c: c['index']):
        bible = (ch.get('summary') or {}).get('bible') or {}
        index = ch['index']
        for c in bible.get('characters') or []:
            rec = ensure(c['name'])
            rec_key = resolve(c['name'])
            for alias in c.get('aliases') or []:
                link_alias(alias, rec_key)
                if alias not in rec['aliases'] and _key(alias) != rec_key:
                    rec['aliases'].append(alias)
            if c.get('identity'):
                rec['identities'][c['identity']] += 1
            rec['importance_votes'][c.get('importance', 'minor')] += 1
            rec['chapters'].add(index)
            for q in c.get('quotes') or []:
                if all(q != x['text'] for x in rec['quotes']):
                    rec['quotes'].append({'chapter': index, 'text': q})
            for r in c.get('reactions') or []:
                rec['reactions'].append({'chapter': index, **r})
            for r in c.get('relations') or []:
                rec['relations'].setdefault((_key(r['target']), r['relation'].lower()), {'chapter': index, **r})
            if c.get('status'):
                rec['timeline'].append({'chapter': index, 'status': c['status']})
        for beat in bible.get('beats') or []:
            plot.append(dict(beat))
        for fact in bible.get('facts') or []:
            fk = _key(fact['content'])
            if fk and fk not in seen_facts:
                seen_facts.add(fk)
                facts.append(dict(fact))

    characters = []
    for rec in records.values():
        chapters = sorted(rec['chapters'])
        votes = rec['importance_votes']
        major = votes['major'] > votes['minor'] or len(chapters) >= MAJOR_MIN_CHAPTERS
        characters.append(
            {
                'name': rec['name'],
                'aliases': rec['aliases'][:8],
                'identity': rec['identities'].most_common(1)[0][0] if rec['identities'] else '',
                'importance': 'major' if major else 'minor',
                'first_chapter': chapters[0] if chapters else 0,
                'last_chapter': chapters[-1] if chapters else 0,
                'chapters': chapters,
                'quotes': sorted(rec['quotes'], key=lambda q: q['chapter'])[:MAX_QUOTES],
                'reactions': sorted(rec['reactions'], key=lambda r: r['chapter'])[:MAX_REACTIONS],
                'relations': sorted(rec['relations'].values(), key=lambda r: r['chapter']),
                'timeline': sorted(rec['timeline'], key=lambda t: t['chapter']),
                'profile': None,  # filled once by LLMService.profile_character
            }
        )
    characters.sort(key=lambda c: (c['importance'] != 'major', -len(c['chapters']), c['first_chapter'], c['name']))
    for n, beat in enumerate(sorted(plot, key=lambda b: (b['chapter'], b['order'])), start=1):
        beat['sequence'] = n
    return {'characters': characters, 'plot': sorted(plot, key=lambda b: b['sequence']), 'facts': facts}


def evidence_signature(character: dict) -> str:
    """Changes whenever the evidence a profile was written from changes, so stale profiles are redone."""
    return f"{len(character.get('chapters', []))}:{len(character.get('quotes', []))}:{len(character.get('reactions', []))}:{len(character.get('timeline', []))}"


def normalize_profile(raw: dict, *, signature: str) -> dict:
    """The single overall profile of a character, as written by the model, forced into the fixed shape."""
    tags = []
    for t in raw.get('style_tags') or []:
        t = _text(t, 20).lower()
        if t in STYLE_TAGS and t not in tags:
            tags.append(t)
    # One side per pair: if the model picked both, keep neither.
    for a, b in STYLE_TAG_PAIRS:
        if a in tags and b in tags:
            tags = [t for t in tags if t not in (a, b)]
    return {
        'personality': _text(raw.get('personality'), 600),
        'speech_style': _text(raw.get('speech_style'), 400),
        'style_tags': tags,
        'behaviour': _strings(raw.get('behaviour') or raw.get('behavior'), limit=160, count=6),
        'signature': signature,
    }


# --- what the narrator sees -------------------------------------------------------


def style_label(tag: str) -> str:
    if str(settings.RPG_OUTPUT_LANGUAGE).lower().startswith(('chinese', 'zh', '中文')):
        return STYLE_TAG_LABELS_ZH.get(tag, tag)
    return tag


def character_sheet(character: dict, *, upto_chapter: int, quotes: int = 8, reactions: int = 5) -> str:
    """One character as prompt text, using only evidence from chapters <= upto_chapter."""
    lines = [f"## {character['name']}" + (f" (aka {', '.join(character['aliases'])})" if character.get('aliases') else '')]
    if character.get('identity'):
        lines.append(f"Identity: {character['identity']}")
    profile = character.get('profile') or {}
    if profile.get('personality'):
        lines.append(f"Personality: {profile['personality']}")
    if profile.get('speech_style'):
        lines.append(f"Speech style: {profile['speech_style']}")
    if profile.get('style_tags'):
        lines.append('Style tags: ' + ', '.join(style_label(t) for t in profile['style_tags']))
    if profile.get('behaviour'):
        lines.append('Typical behaviour: ' + ' | '.join(profile['behaviour']))
    timeline = [t for t in character.get('timeline', []) if t['chapter'] <= upto_chapter]
    if timeline:
        lines.append('Status so far: ' + ' | '.join(f"ch{t['chapter']}: {t['status']}" for t in timeline[-5:]))
    rel = [r for r in character.get('relations', []) if r['chapter'] <= upto_chapter]
    if rel:
        lines.append('Relations: ' + '; '.join(f"{r['target']}: {r['relation']}" for r in rel[:8]))
    qs = [q for q in character.get('quotes', []) if q['chapter'] <= upto_chapter][-quotes:]
    if qs:
        lines.append('Actual lines from the book: ' + ' / '.join(f"“{q['text']}”" for q in qs))
    rs = [r for r in character.get('reactions', []) if r['chapter'] <= upto_chapter][-reactions:]
    if rs:
        lines.append('Observed reactions: ' + ' | '.join(f"{r['situation']} -> {r['action']}" if r['situation'] else r['action'] for r in rs))
    return '\n'.join(lines)


def narrator_context(
    *, characters: list[dict], plot: list[dict], facts: list[dict], chapter: int, present: list[str], max_chars: int = 7000
) -> str:
    """Bible text for one turn: present characters' sheets, this chapter's beats, rules known so far."""
    present_keys = {_key(p) for p in present}
    sheets = [
        c for c in characters
        if c.get('first_chapter', 1) <= chapter
        and ({_key(c['name']), *(_key(a) for a in c.get('aliases', []))} & present_keys or (c['importance'] == 'major' and chapter in c.get('chapters', [])))
    ]
    parts = []
    beats = [b for b in plot if b['chapter'] == chapter]
    if beats:
        parts.append('Key beats of the current chapter, in order:\n' + '\n'.join(f"{i}. [{b['type']}] {b['description']}" + (f" -> {b['consequence']}" if b.get('consequence') else '') for i, b in enumerate(beats, 1)))
    known = [f for f in facts if f['chapter'] <= chapter]
    if known:
        parts.append('Established rules and facts (known by this point):\n' + '\n'.join(f"- ({f['category']}) {f['content']}" for f in known[-25:]))
    if sheets:
        parts.append(
            'Character bible (ground truth for how each person speaks and acts; staying silent or answering in a word '
            'is correct when it fits them; never reveal anything from later chapters):\n'
            + '\n\n'.join(character_sheet(c, upto_chapter=chapter) for c in sheets[:8])
        )
    text = '\n\n'.join(parts)
    return text[:max_chars]
