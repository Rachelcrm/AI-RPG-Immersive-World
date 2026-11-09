from __future__ import annotations

from datetime import datetime, timezone

from django.conf import settings
from pymongo import ASCENDING, MongoClient

MAX_CHAPTER_ATTEMPTS = 3


class MongoService:
    # Dev fallback when MONGODB_URI is empty: keep turn history and chapter data in process
    # memory so the narrator still sees earlier turns (terminal play, single runserver). Lost on
    # restart and not shared between gunicorn workers -- configure MongoDB for real deployments.
    _memory_history: dict[int, list[dict]] = {}
    _memory_chapters: dict[str, list[dict]] = {}
    _memory_bible: dict[str, dict] = {}

    @staticmethod
    def _get_client() -> MongoClient | None:
        if not settings.MONGODB_URI:
            return None
        return MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=3000)

    @classmethod
    def _get_collection(cls, name: str):
        client = cls._get_client()
        if client is None:
            return None
        return client[settings.MONGODB_DB_NAME][name]

    @staticmethod
    def ping() -> dict:
        if not settings.MONGODB_URI:
            return {'ok': False, 'message': 'MONGODB_URI is not configured.'}
        try:
            client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=3000)
            client.admin.command('ping')
            return {'ok': True, 'message': f'MongoDB connected: {settings.MONGODB_DB_NAME}'}
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}

    # --- conversation history ---------------------------------------------

    @classmethod
    def insert_conversation_log(
        cls,
        *,
        session_id: int,
        world_id: int,
        character_id: int,
        user_input: str,
        ai_output: str,
    ) -> dict:
        collection = cls._get_collection('conversation_logs')
        if collection is None:
            cls._memory_history.setdefault(session_id, []).append({'user_input': user_input, 'ai_output': ai_output})
            return {'ok': False, 'message': 'MONGODB_URI is not configured; history kept in process memory.'}
        try:
            result = collection.insert_one(
                {
                    'session_id': session_id,
                    'world_id': world_id,
                    'character_id': character_id,
                    'user_input': user_input,
                    'ai_output': ai_output,
                }
            )
            return {'ok': True, 'id': str(result.inserted_id)}
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}

    @classmethod
    def insert_event_log(cls, *, session_id: int, character_id: int, event: dict) -> dict:
        collection = cls._get_collection('game_events')
        if collection is None:
            return {'ok': False, 'message': 'MONGODB_URI is not configured.'}
        try:
            result = collection.insert_one({'session_id': session_id, 'character_id': character_id, **event})
            return {'ok': True, 'id': str(result.inserted_id)}
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}

    @classmethod
    def get_conversation_history(cls, *, session_id: int, limit: int = 8) -> list[dict]:
        collection = cls._get_collection('conversation_logs')
        if collection is None:
            return list(cls._memory_history.get(session_id, [])[-limit:])
        docs = (
            collection.find({'session_id': session_id}, {'_id': 0, 'user_input': 1, 'ai_output': 1})
            .sort('_id', -1)
            .limit(limit)
        )
        history = list(docs)
        history.reverse()
        return history

    # --- chapters ----------------------------------------------------------
    # One document per chapter: {book_id, index, title, text, status, attempts, summary, error}.
    # status is 'pending' | 'done' | 'failed'. A failed chapter is retried until MAX_CHAPTER_ATTEMPTS.

    @classmethod
    def _chapters(cls):
        collection = cls._get_collection('chapters')
        if collection is not None:
            collection.create_index([('book_id', ASCENDING), ('index', ASCENDING)], unique=True)
        return collection

    @classmethod
    def upsert_chapters(cls, *, book_id: str, chapters: list[dict]) -> int:
        """Insert pending chapter docs; chapters that already exist are left untouched."""
        docs = [
            {
                'book_id': book_id,
                'index': ch['index'],
                'title': ch['title'],
                'text': ch['text'],
                'status': 'pending',
                'attempts': 0,
                'summary': None,
                'error': '',
            }
            for ch in chapters
        ]
        collection = cls._chapters()
        if collection is None:
            existing = {d['index'] for d in cls._memory_chapters.get(book_id, [])}
            new = [d for d in docs if d['index'] not in existing]
            cls._memory_chapters.setdefault(book_id, []).extend(new)
            cls._memory_chapters[book_id].sort(key=lambda d: d['index'])
            return len(new)
        inserted = 0
        for doc in docs:
            result = collection.update_one(
                {'book_id': book_id, 'index': doc['index']}, {'$setOnInsert': doc}, upsert=True
            )
            inserted += 1 if result.upserted_id is not None else 0
        return inserted

    @classmethod
    def pending_chapters(cls, *, book_id: str, limit: int) -> list[dict]:
        """Chapters still to summarise, retriable failures included, lowest index first."""

        def retriable(doc: dict) -> bool:
            return doc['status'] == 'pending' or (
                doc['status'] == 'failed' and doc.get('attempts', 0) < MAX_CHAPTER_ATTEMPTS
            )

        collection = cls._chapters()
        if collection is None:
            docs = [d for d in cls._memory_chapters.get(book_id, []) if retriable(d)]
        else:
            docs = list(
                collection.find(
                    {
                        'book_id': book_id,
                        '$or': [
                            {'status': 'pending'},
                            {'status': 'failed', 'attempts': {'$lt': MAX_CHAPTER_ATTEMPTS}},
                        ],
                    },
                    {'_id': 0, 'index': 1, 'title': 1, 'text': 1, 'attempts': 1},
                ).sort('index', ASCENDING)
            )
        return [{'index': d['index'], 'title': d['title'], 'text': d['text']} for d in docs[:limit]]

    @classmethod
    def save_chapter_summary(cls, *, book_id: str, index: int, summary: dict) -> None:
        cls._update_chapter(book_id, index, {'status': 'done', 'summary': summary, 'error': ''})

    @classmethod
    def mark_chapter_failed(cls, *, book_id: str, index: int, error: str) -> None:
        cls._update_chapter(book_id, index, {'status': 'failed', 'error': error[:500]}, bump_attempts=True)

    @classmethod
    def _update_chapter(cls, book_id: str, index: int, fields: dict, *, bump_attempts: bool = False) -> None:
        fields = {**fields, 'updated_at': datetime.now(timezone.utc)}
        collection = cls._chapters()
        if collection is None:
            for doc in cls._memory_chapters.get(book_id, []):
                if doc['index'] == index:
                    doc.update(fields)
                    if bump_attempts:
                        doc['attempts'] = doc.get('attempts', 0) + 1
            return
        update: dict = {'$set': fields}
        if bump_attempts:
            update['$inc'] = {'attempts': 1}
        collection.update_one({'book_id': book_id, 'index': index}, update)

    @classmethod
    def chapter_progress(cls, *, book_id: str) -> dict:
        """{'total', 'done', 'failed', 'pending'}; failed = gave up after MAX_CHAPTER_ATTEMPTS."""
        collection = cls._chapters()
        if collection is None:
            docs = [
                {'status': d['status'], 'attempts': d.get('attempts', 0)} for d in cls._memory_chapters.get(book_id, [])
            ]
        else:
            docs = list(collection.find({'book_id': book_id}, {'_id': 0, 'status': 1, 'attempts': 1}))
        done = sum(1 for d in docs if d['status'] == 'done')
        failed = sum(1 for d in docs if d['status'] == 'failed' and d.get('attempts', 0) >= MAX_CHAPTER_ATTEMPTS)
        total = len(docs)
        return {'total': total, 'done': done, 'failed': failed, 'pending': total - done - failed}

    @classmethod
    def get_chapter_summaries(cls, *, book_id: str, indexes: list[int] | None = None) -> list[dict]:
        """Finished summaries as [{'index', 'title', 'summary'}], ordered by index."""
        collection = cls._chapters()
        if collection is None:
            docs = [d for d in cls._memory_chapters.get(book_id, []) if d['status'] == 'done']
            if indexes is not None:
                docs = [d for d in docs if d['index'] in set(indexes)]
        else:
            query: dict = {'book_id': book_id, 'status': 'done'}
            if indexes is not None:
                query['index'] = {'$in': list(indexes)}
            docs = list(
                collection.find(query, {'_id': 0, 'index': 1, 'title': 1, 'summary': 1}).sort('index', ASCENDING)
            )
        return [{'index': d['index'], 'title': d['title'], 'summary': d['summary']} for d in docs]

    @classmethod
    def export_chapters(cls, *, book_id: str) -> list[dict]:
        """Every chapter document of a book (text, status, attempts, summary), ordered by index."""
        collection = cls._chapters()
        if collection is None:
            docs = [dict(d) for d in cls._memory_chapters.get(book_id, [])]
        else:
            docs = list(collection.find({'book_id': book_id}, {'_id': 0}).sort('index', ASCENDING))
        for d in docs:
            d.pop('book_id', None)
            if isinstance(d.get('updated_at'), datetime):
                d['updated_at'] = d['updated_at'].isoformat()
        return docs

    @classmethod
    def import_chapters(cls, *, book_id: str, docs: list[dict]) -> int:
        """Replace a book's chapters with exported documents. Returns the number stored."""
        cleaned = []
        for d in docs:
            doc = {
                'book_id': book_id,
                'index': int(d['index']),
                'title': d.get('title', ''),
                'text': d.get('text', ''),
                'status': d.get('status', 'pending'),
                'attempts': int(d.get('attempts', 0)),
                'summary': d.get('summary'),
                'error': d.get('error', ''),
            }
            if d.get('updated_at'):
                try:
                    doc['updated_at'] = datetime.fromisoformat(d['updated_at'])
                except (TypeError, ValueError):
                    pass
            cleaned.append(doc)
        cleaned.sort(key=lambda d: d['index'])
        cls.delete_chapters(book_id=book_id)
        collection = cls._chapters()
        if collection is None:
            cls._memory_chapters[book_id] = cleaned
        elif cleaned:
            collection.insert_many(cleaned)
        return len(cleaned)

    @classmethod
    def reset_chapters(cls, *, book_id: str) -> int:
        """Mark every chapter pending again (text kept) so the next scan redoes the summaries. Returns the count."""
        fields = {'status': 'pending', 'attempts': 0, 'summary': None, 'error': '', 'updated_at': datetime.now(timezone.utc)}
        collection = cls._chapters()
        if collection is None:
            docs = cls._memory_chapters.get(book_id, [])
            for doc in docs:
                doc.update(fields)
            return len(docs)
        return collection.update_many({'book_id': book_id}, {'$set': fields}).modified_count

    @classmethod
    def delete_chapters(cls, *, book_id: str) -> None:
        collection = cls._chapters()
        if collection is None:
            cls._memory_chapters.pop(book_id, None)
            return
        collection.delete_many({'book_id': book_id})

    # --- story bible ---------------------------------------------------------
    # Per-book hard facts derived from the chapter scan (see services/bible.py):
    #   characters  {book_id, name, aliases, identity, importance, chapters, quotes, reactions, relations, timeline, profile}
    #   plot        {book_id, sequence, chapter, order, type, description, participants, consequence}
    #   facts       {book_id, chapter, category, content}
    #   bible_meta  {book_id, done_chapters, built_at}

    BIBLE_COLLECTIONS = ('characters', 'plot', 'facts')

    @classmethod
    def _bible_collection(cls, name: str):
        collection = cls._get_collection(name)
        if collection is not None:
            collection.create_index([('book_id', ASCENDING)])
        return collection

    @classmethod
    def replace_bible(cls, *, book_id: str, bible: dict, done_chapters: int) -> None:
        """Store the merged bible for a book, replacing whatever was there. Profiles are kept on name match."""
        old_profiles = {c['name']: c.get('profile') for c in cls.get_characters(book_id=book_id) if c.get('profile')}
        characters = [dict(c, profile=c.get('profile') or old_profiles.get(c['name'])) for c in bible['characters']]
        meta = {'done_chapters': done_chapters, 'built_at': datetime.now(timezone.utc)}
        if cls._get_client() is None:
            cls._memory_bible[book_id] = {'characters': characters, 'plot': list(bible['plot']), 'facts': list(bible['facts']), 'meta': meta}
            return
        for name, docs in (('characters', characters), ('plot', bible['plot']), ('facts', bible['facts'])):
            collection = cls._bible_collection(name)
            collection.delete_many({'book_id': book_id})
            if docs:
                collection.insert_many([{'book_id': book_id, **d} for d in docs])
        cls._get_collection('bible_meta').update_one({'book_id': book_id}, {'$set': meta}, upsert=True)

    @classmethod
    def bible_meta(cls, *, book_id: str) -> dict | None:
        if cls._get_client() is None:
            entry = cls._memory_bible.get(book_id)
            return entry['meta'] if entry else None
        return cls._get_collection('bible_meta').find_one({'book_id': book_id}, {'_id': 0, 'book_id': 0})

    @classmethod
    def _bible_docs(cls, name: str, *, book_id: str, query: dict | None = None, sort: str | None = None) -> list[dict]:
        if cls._get_client() is None:
            docs = [dict(d) for d in (cls._memory_bible.get(book_id) or {}).get(name, [])]
            for k, v in (query or {}).items():
                docs = [d for d in docs if d.get(k) == v]
        else:
            cursor = cls._bible_collection(name).find({'book_id': book_id, **(query or {})}, {'_id': 0, 'book_id': 0})
            docs = list(cursor.sort(sort, ASCENDING) if sort else cursor)
        if sort:
            docs.sort(key=lambda d: d.get(sort, 0))
        return docs

    @classmethod
    def get_characters(cls, *, book_id: str, importance: str | None = None) -> list[dict]:
        """Character records, major ones first, then by how many chapters they appear in."""
        docs = cls._bible_docs('characters', book_id=book_id, query={'importance': importance} if importance else None)
        docs.sort(key=lambda c: (c.get('importance') != 'major', -len(c.get('chapters', [])), c.get('first_chapter', 0), c.get('name', '')))
        return docs

    @classmethod
    def get_plot(cls, *, book_id: str, chapter: int | None = None) -> list[dict]:
        return cls._bible_docs('plot', book_id=book_id, query={'chapter': chapter} if chapter is not None else None, sort='sequence')

    @classmethod
    def get_facts(cls, *, book_id: str) -> list[dict]:
        return cls._bible_docs('facts', book_id=book_id, sort='chapter')

    @classmethod
    def save_character_profile(cls, *, book_id: str, name: str, profile: dict) -> None:
        if cls._get_client() is None:
            for c in (cls._memory_bible.get(book_id) or {}).get('characters', []):
                if c['name'] == name:
                    c['profile'] = profile
            return
        cls._bible_collection('characters').update_one({'book_id': book_id, 'name': name}, {'$set': {'profile': profile}})

    @classmethod
    def export_bible(cls, *, book_id: str) -> dict:
        return {
            'characters': cls.get_characters(book_id=book_id),
            'plot': cls.get_plot(book_id=book_id),
            'facts': cls.get_facts(book_id=book_id),
        }

    @classmethod
    def delete_bible(cls, *, book_id: str) -> None:
        if cls._get_client() is None:
            cls._memory_bible.pop(book_id, None)
            return
        for name in cls.BIBLE_COLLECTIONS:
            cls._bible_collection(name).delete_many({'book_id': book_id})
        cls._get_collection('bible_meta').delete_many({'book_id': book_id})
