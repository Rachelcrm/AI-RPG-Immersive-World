"""Turn a Book into a playable World in resumable steps.

    ingest_book(book)            split the text into chapters (MongoDB `chapters`), no model calls
    process_chapters(book, ai)   summarise the next batch of pending chapters, concurrently
    ensure_bible(book, ai)       merge the chapters' evidence into the story bible, profile major characters
    build_world_from_book(...)   world spec + locations + NPCs (the book's major characters) + market

Every step is idempotent, so a caller can drive the pipeline one short HTTP
request at a time (the web UI polls `/api/play/prepare/`) or run it to
completion in one process (the terminal `play` command, `prepare_book`).
Shared by both entry points so they create identical worlds.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.conf import settings

from game.models import Book, MarketItem, Merchant, MerchantInventory, World
from game.services.bible import evidence_signature, merge_bible
from game.services.chapters import split_chapters
from game.services.factories import ComponentFactoryRegistry
from game.services.llm_service import LLMService
from game.services.mongo_service import MongoService
from game.services.rule_layer import MarketRuleLayer

Log = Callable[[str], None]
DEFAULT_BATCH = 6  # chapters summarised per process_chapters() call
MAX_WORKERS = 6  # concurrent model calls inside one batch
LOCAL_SOURCE = 'local'
MAX_PROFILES = 24  # major characters that get an overall profile (one model call each)
MAX_BOOK_NPCS = 8  # major characters seeded as NPCs when a world is built


def _noop(_msg: str) -> None:
    pass


# --- local book files -------------------------------------------------------


def list_local_books() -> list[dict]:
    """The .txt books under settings.BOOKS_DIR, as {'file': name, 'title': stem}."""
    books_dir = Path(settings.BOOKS_DIR)
    if not books_dir.is_dir():
        return []
    return [{'file': p.name, 'title': p.stem} for p in sorted(books_dir.glob('*.txt')) if p.is_file()]


def resolve_local_book(file_name: str) -> Path | None:
    """Path of a book inside BOOKS_DIR, or None if it is missing or escapes the folder."""
    books_dir = Path(settings.BOOKS_DIR).resolve()
    path = (books_dir / file_name).resolve()
    if path.parent != books_dir or path.suffix != '.txt' or not path.is_file():
        return None
    return path


def book_for_local_file(path: Path) -> Book:
    """The Book row for a local file, created on first use so chapter progress survives between requests."""
    book = Book.objects.filter(title=path.stem, source_type=LOCAL_SOURCE).order_by('-id').first()
    if book is None:
        content = path.read_text(encoding='utf-8', errors='ignore')
        book = Book.objects.create(title=path.stem, content=content, source_type=LOCAL_SOURCE)
    return book


# --- chapter pipeline -------------------------------------------------------


def ingest_book(book: Book) -> dict:
    """Split the book into chapters once; returns chapter progress.

    Without MongoDB the chapters live in process memory, so after a restart the Book still says
    `chapter_count` but the store is empty: split again so the summaries can be rebuilt.
    """
    if book.chapter_count == 0 or MongoService.chapter_progress(book_id=book.store_key)['total'] == 0:
        chapters = split_chapters(book.content, group_chars=settings.CHAPTER_GROUP_CHARS)
        MongoService.upsert_chapters(
            book_id=book.store_key, chapters=[{'index': c.index, 'title': c.title, 'text': c.text} for c in chapters]
        )
        book.chapter_count = len(chapters)
        book.save(update_fields=['chapter_count', 'updated_at'])
    return MongoService.chapter_progress(book_id=book.store_key)


def process_chapters(book: Book, ai: LLMService, *, batch: int = DEFAULT_BATCH, info: Log = _noop) -> dict:
    """Summarise up to `batch` pending chapters concurrently and store the results. Returns progress."""
    pending = MongoService.pending_chapters(book_id=book.store_key, limit=batch)
    if not pending:
        return MongoService.chapter_progress(book_id=book.store_key)
    previous = {
        ch['index']: ch['summary'].get('summary', '')
        for ch in MongoService.get_chapter_summaries(book_id=book.store_key, indexes=[c['index'] - 1 for c in pending])
    }

    def summarise(chapter: dict) -> tuple[dict, dict | None, str]:
        try:
            summary = ai.summarize_chapter(
                book_title=book.title,
                chapter_index=chapter['index'],
                chapter_count=book.chapter_count,
                chapter_title=chapter['title'],
                text=chapter['text'],
                previous_summary=previous.get(chapter['index'] - 1, ''),
            )
            return chapter, summary, ''
        except Exception as exc:  # recorded per chapter; the batch carries on
            return chapter, None, str(exc)

    # Only Mongo and the model are touched inside the threads, never the Django ORM.
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(pending))) as pool:
        for chapter, summary, error in pool.map(summarise, pending):
            if summary is not None:
                MongoService.save_chapter_summary(book_id=book.store_key, index=chapter['index'], summary=summary)
                info(f"Chapter {chapter['index']}/{book.chapter_count} summarised: {chapter['title']}")
            else:
                MongoService.mark_chapter_failed(book_id=book.store_key, index=chapter['index'], error=error)
                info(f"Chapter {chapter['index']}/{book.chapter_count} failed: {error}")
    return MongoService.chapter_progress(book_id=book.store_key)


def prepare_book(book: Book, ai: LLMService, *, batch: int = DEFAULT_BATCH, info: Log = _noop) -> dict:
    """Run ingest + every remaining batch to completion (terminal / tests). Returns final progress."""
    progress = ingest_book(book)
    while progress['pending']:
        progress = process_chapters(book, ai, batch=batch, info=info)
    while ensure_bible(book, ai, batch=batch, info=info):
        pass
    return progress


# --- story bible -----------------------------------------------------------------


def rebuild_bible(book: Book) -> dict:
    """Merge every summarised chapter's evidence into the characters / plot / facts records. No model calls.

    Existing character profiles survive the rebuild (matched by name); whether they are still
    current is decided by `evidence_signature` in `profile_characters`.
    """
    summaries = MongoService.get_chapter_summaries(book_id=book.store_key)
    merged = merge_bible(summaries)
    MongoService.replace_bible(book_id=book.store_key, bible=merged, done_chapters=len(summaries))
    return {'characters': len(merged['characters']), 'plot': len(merged['plot']), 'facts': len(merged['facts'])}


def characters_needing_profile(book: Book) -> list[dict]:
    """Major characters whose overall profile is missing or was written from older evidence."""
    return [
        c
        for c in MongoService.get_characters(book_id=book.store_key, importance='major')[:MAX_PROFILES]
        if (c.get('profile') or {}).get('signature') != evidence_signature(c)
    ]


def profile_characters(book: Book, ai: LLMService, *, batch: int = DEFAULT_BATCH, info: Log = _noop) -> int:
    """Write the one overall profile for up to `batch` major characters, concurrently. Returns how many remain.

    A failed call is recorded on the character (with the current signature) so it is not retried
    on every poll; `chapters_reset` or new evidence clears it.
    """
    todo = characters_needing_profile(book)
    if not todo:
        return 0
    chunk = todo[:batch]

    def profile(character: dict) -> tuple[dict, dict]:
        signature = evidence_signature(character)
        try:
            return character, ai.profile_character(book_title=book.title, character=character)
        except Exception as exc:
            return character, {'signature': signature, 'error': str(exc)[:300]}

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(chunk))) as pool:
        for character, result in pool.map(profile, chunk):
            MongoService.save_character_profile(book_id=book.store_key, name=character['name'], profile=result)
            info(f"Profile {'failed' if result.get('error') else 'written'}: {character['name']}")
    return len(todo) - len(chunk)


def ensure_bible(book: Book, ai: LLMService, *, batch: int = DEFAULT_BATCH, info: Log = _noop) -> int:
    """Bring the bible up to date with the summarised chapters. Returns the number of profiles still to write."""
    progress = MongoService.chapter_progress(book_id=book.store_key)
    meta = MongoService.bible_meta(book_id=book.store_key)
    if meta is None or meta.get('done_chapters') != progress['done']:
        stats = rebuild_bible(book)
        info(f"Bible: {stats['characters']} characters, {stats['plot']} plot beats, {stats['facts']} facts")
    return profile_characters(book, ai, batch=batch, info=info)


def chapter_list(book: Book) -> list[dict]:
    """Finished chapter summaries for the chapter picker: index, title and the plot digest."""
    rows = []
    for ch in MongoService.get_chapter_summaries(book_id=book.store_key):
        s = ch.get('summary') or {}
        rows.append(
            {
                'book_key': book.store_key,
                'index': ch['index'],
                'title': ch['title'],
                'summary': s.get('summary', ''),
                'locations': s.get('locations', []),
                'characters': [c['name'] for c in s.get('characters', [])],
                'events': s.get('events', []),
            }
        )
    return rows


def opening_objective(chapter: dict | None) -> str:
    """First hint under the input box: the chapter's first open thread, if the scan recorded one."""
    if not chapter:
        return ''
    hooks = MongoService.get_chapter_summaries(book_id=chapter['book_key'], indexes=[chapter['index']]) if chapter.get('book_key') else []
    hook = ((hooks[0].get('summary') or {}).get('hooks') or [''])[0] if hooks else ''
    return str(hook).strip()[:120]


def starting_location(world: World, chapter: int) -> str:
    """Where a character starts when the story begins at `chapter`.

    The first place that chapter's summary names and the world knows; else the first place the
    summary names at all; else the world's first location.
    """
    fallback = (world.locations or [''])[0]
    if not world.book_id:
        return fallback
    summaries = MongoService.get_chapter_summaries(book_id=world.book.store_key, indexes=[chapter])
    if not summaries:
        return fallback
    named = (summaries[0].get('summary') or {}).get('locations') or []
    known = {str(loc).strip().lower(): str(loc) for loc in (world.locations or [])}
    for loc in named:
        hit = known.get(str(loc).strip().lower())
        if hit:
            return hit
    return str(named[0]) if named else fallback


# --- world -----------------------------------------------------------------


def build_world_from_file(path: Path, ai: LLMService, *, info: Log = _noop, warn: Log = _noop) -> World:
    """Whole pipeline in one call: chapters, summaries, then the world."""
    book = book_for_local_file(path)
    progress = prepare_book(book, ai, info=info)
    info(f"Chapters: {progress['done']} summarised, {progress['failed']} failed, {progress['total']} total")
    return build_world_from_book(book, ai, info=info, warn=warn)


def build_world_from_book(book: Book, ai: LLMService, *, info: Log = _noop, warn: Log = _noop) -> World:
    """`info` / `warn` receive progress lines (the terminal prints them, the web endpoint ignores them).

    Uses the chapter summaries when the book has been through the pipeline; otherwise the
    model only sees the opening excerpt of the text.
    """
    summaries = MongoService.get_chapter_summaries(book_id=book.store_key)
    if not summaries:
        warn('No chapter summaries found; building the world from the opening excerpt only.')
    spec = ai.generate_world(book_title=book.title, book_content=book.content, chapter_summaries=summaries)
    world = World.objects.create(
        book=book,
        name=spec['world_name'],
        source_book_title=book.title,
        lore_summary=spec['lore_summary'],
        factions=spec['factions'],
        locations=spec['locations'],
        main_conflict=spec['main_conflict'],
    )
    loc_factory = ComponentFactoryRegistry.get('location', ai=ai)
    for name in spec['locations']:
        try:
            loc_factory.create(world=world, spec={'name': name})
        except ValueError:
            continue
    try:
        npcs = seed_book_npcs(world, book) or ComponentFactoryRegistry.get('npc', ai=ai).create_many(world=world, count=3)
        info(f'NPCs: {", ".join(n.name for n in npcs)}')
    except Exception as exc:
        warn(f'NPC generation skipped: {exc}')
    bootstrap_market(world, book, ai, summaries=summaries, info=info, warn=warn)
    return world


def seed_book_npcs(world: World, book: Book) -> list:
    """NPCs for the book's major characters, placed where they first appear. Empty when the bible has none."""
    factory = ComponentFactoryRegistry.get('npc')
    npcs = []
    for c in MongoService.get_characters(book_id=book.store_key, importance='major')[:MAX_BOOK_NPCS]:
        profile = c.get('profile') or {}
        description = ' '.join(p for p in (profile.get('personality'), profile.get('speech_style')) if p)
        try:
            npcs.append(
                factory.create(
                    world=world,
                    spec={
                        'name': c['name'],
                        'role': c.get('identity', ''),
                        'location': starting_location(world, c.get('first_chapter') or 1),
                        'disposition': 'neutral',
                        'description': description,
                    },
                )
            )
        except ValueError:
            continue
    return npcs


def bootstrap_market(
    world: World,
    book: Book,
    ai: LLMService,
    *,
    summaries: list[dict] | None = None,
    info: Log = _noop,
    warn: Log = _noop,
) -> None:
    try:
        data = ai.generate_market_candidates(
            world_name=world.name,
            world_lore_summary=world.lore_summary,
            book_title=book.title,
            book_content=book.content,
            chapter_summaries=summaries or [],
        )
    except Exception as exc:
        warn(f'Market generation skipped: {exc}')
        return
    items = MarketRuleLayer.sanitize_items(data.get('items', []))
    merchants = MarketRuleLayer.sanitize_merchants(data.get('merchants', []))
    item_objs = []
    for item in items:
        obj, _ = MarketItem.objects.update_or_create(
            world=world,
            name=item['name'],
            defaults={'category': item['category'], 'rarity': item['rarity'], 'base_price': item['base_price']},
        )
        item_objs.append((obj, item['stock']))
    first_location = (world.locations or [''])[0]
    for m in merchants:
        merchant, _ = Merchant.objects.update_or_create(
            world=world,
            name=m['name'],
            defaults={
                'location': m['location'] or first_location,
                'price_multiplier': m['price_multiplier'],
                'buyback_rate': m['buyback_rate'],
            },
        )
        for obj, stock in item_objs:
            MerchantInventory.objects.update_or_create(merchant=merchant, market_item=obj, defaults={'stock': stock})
    info(f'Market: {len(item_objs)} items, {len(merchants)} merchant(s)')
