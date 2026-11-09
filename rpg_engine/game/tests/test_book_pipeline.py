"""The resumable chapter pipeline: split -> summarise in batches -> build world."""
from unittest.mock import patch

import pytest

from game.models import Book, StorySession, World
from game.services.mongo_service import MongoService
from game.services.offline_narrator import OfflineNarrator
from game.services.story_service import StoryService
from game.services.world_builder import ingest_book, prepare_book, process_chapters

pytestmark = pytest.mark.django_db

PARA = 'Allan Quatermain met Sir Henry Curtis aboard the ship. ' * 10
THREE_CHAPTERS = f'CHAPTER I\n{PARA}\n\nCHAPTER II\n{PARA}\n\nCHAPTER III\n{PARA}'


@pytest.fixture(autouse=True)
def one_summary_per_chapter(settings):
    # The test books have ~550-char chapters; grouping would fold them into one unit.
    settings.CHAPTER_GROUP_CHARS = 0


@pytest.fixture
def books_dir(settings, tmp_path):
    (tmp_path / 'mines.txt').write_text(THREE_CHAPTERS, encoding='utf-8')
    settings.BOOKS_DIR = tmp_path
    return tmp_path


@pytest.fixture
def offline_llm():
    with patch('game.views.get_llm_service', return_value=OfflineNarrator()):
        yield


# --- service layer ------------------------------------------------------------


def test_ingest_splits_once_and_is_idempotent():
    book = Book.objects.create(title='mines', content=THREE_CHAPTERS)
    assert ingest_book(book) == {'total': 3, 'done': 0, 'failed': 0, 'pending': 3}
    assert book.chapter_count == 3
    assert ingest_book(book)['total'] == 3  # second call does not duplicate chapters


def test_process_chapters_summarises_in_batches_and_passes_previous_summary():
    book = Book.objects.create(title='mines', content=THREE_CHAPTERS)
    ingest_book(book)
    ai = OfflineNarrator()
    with patch.object(ai, 'summarize_chapter', wraps=ai.summarize_chapter) as spy:
        first = process_chapters(book, ai, batch=2)
        second = process_chapters(book, ai, batch=2)
    assert first == {'total': 3, 'done': 2, 'failed': 0, 'pending': 1}
    assert second == {'total': 3, 'done': 3, 'failed': 0, 'pending': 0}
    assert spy.call_count == 3
    assert spy.call_args_list[2].kwargs['chapter_index'] == 3
    assert spy.call_args_list[2].kwargs['previous_summary']  # chapter 2's summary was available
    summaries = MongoService.get_chapter_summaries(book_id=book.store_key)
    assert [s['index'] for s in summaries] == [1, 2, 3]
    assert summaries[0]['summary']['summary'].startswith('Allan Quatermain')


def test_failed_chapters_are_retried_then_given_up():
    book = Book.objects.create(title='mines', content=THREE_CHAPTERS)
    ai = OfflineNarrator()
    calls = {'n': 0}

    def flaky(*, chapter_index, **kwargs):
        calls['n'] += 1
        if chapter_index == 2:
            raise RuntimeError('model down')
        return {'summary': f'ch{chapter_index}', 'characters': [], 'locations': [], 'items': [], 'events': [], 'hooks': []}

    with patch.object(ai, 'summarize_chapter', side_effect=flaky):
        progress = prepare_book(book, ai, batch=3)
    assert progress == {'total': 3, 'done': 2, 'failed': 1, 'pending': 0}
    assert calls['n'] == 3 + 2  # chapter 2 tried three times in total
    assert [s['index'] for s in MongoService.get_chapter_summaries(book_id=book.store_key)] == [1, 3]


def test_world_is_built_from_chapter_digest():
    book = Book.objects.create(title='mines', content=THREE_CHAPTERS)
    ai = OfflineNarrator()
    prepare_book(book, ai)
    with patch.object(ai, 'generate_world', wraps=ai.generate_world) as spy:
        from game.services.world_builder import build_world_from_book

        world = build_world_from_book(book, ai)
    digest = spy.call_args.kwargs['chapter_summaries']
    assert [d['index'] for d in digest] == [1, 2, 3]
    assert world.book_id == book.id


# --- web API ---------------------------------------------------------------------


def test_play_prepare_polls_until_world_is_ready(api, books_dir, offline_llm):
    first = api.post('/api/play/prepare/', {'book': 'mines.txt', 'batch': 2}, format='json').json()
    assert first['ready'] is False
    assert (first['total'], first['done'], first['pending']) == (3, 2, 1)

    second = api.post('/api/play/prepare/', {'book': 'mines.txt', 'batch': 2}, format='json').json()
    assert second['ready'] is True
    assert second['done'] == 3
    assert World.objects.filter(id=second['world_id'], book__title='mines').exists()

    with patch('game.views.process_chapters') as proc, patch('game.views.build_world_from_book') as build:
        third = api.post('/api/play/prepare/', {'book': 'mines.txt'}, format='json').json()
    assert third['ready'] is True and third['world_id'] == second['world_id']
    proc.assert_not_called()
    build.assert_not_called()
    assert Book.objects.filter(title='mines').count() == 1

    start = api.post('/api/play/start/', {'book': 'mines.txt', 'name': 'Allan'}, format='json')
    assert start.status_code == 201
    assert start.json()['world']['id'] == second['world_id']
    assert start.json()['state']['chapter'] == 1
    assert start.json()['state']['chapter_count'] == 3


def test_play_prepare_rejects_unknown_book(api, books_dir, offline_llm):
    assert api.post('/api/play/prepare/', {'book': 'nope.txt'}, format='json').status_code == 404


def test_play_prepare_returns_502_when_world_generation_fails(api, books_dir):
    ai = OfflineNarrator()
    with patch('game.views.get_llm_service', return_value=ai), patch.object(ai, 'generate_world', side_effect=ValueError('no key')):
        resp = api.post('/api/play/prepare/', {'book': 'mines.txt', 'batch': 10}, format='json')
    assert resp.status_code == 502
    assert resp.json()['done'] == 3  # chapter work is kept; only the world step failed
    assert World.objects.count() == 0


def test_uploaded_book_can_be_processed_and_polled(api, offline_llm):
    book_id = api.post('/api/books/upload/', {'title': 'mines', 'content': THREE_CHAPTERS}, format='json').json()['book']['id']
    progress = api.get(f'/api/books/{book_id}/process/').json()
    assert progress == {
        'book_id': book_id, 'book_title': 'mines', 'chapter_count': 0,
        'total': 0, 'done': 0, 'failed': 0, 'pending': 0, 'profiles_pending': 0, 'ready': False, 'world_id': None,
    }
    step = api.post(f'/api/books/{book_id}/process/', {'batch': 20}, format='json').json()
    assert step['ready'] is True and step['done'] == 3
    assert api.post('/api/books/999/process/', {}, format='json').status_code == 404


# --- story turns ----------------------------------------------------------------


@pytest.fixture
def chaptered_session(book, world, character, session):
    book.content = THREE_CHAPTERS
    book.save()
    prepare_book(book, OfflineNarrator())
    session.current_chapter = 2
    session.save()
    return session


def test_turn_prompt_carries_neighbouring_chapter_summaries(chaptered_session):
    context = StoryService.chapter_context(chaptered_session)
    assert 'Main conflict: Who controls the last flame.' in context
    assert 'currently in chapter 2 of 3' in context
    assert 'Chapter 1 - CHAPTER I' in context and 'Chapter 3 - CHAPTER III' in context

    ai = OfflineNarrator()
    with patch.object(ai, 'generate_story_turn', return_value={'narrative': 'ok', 'events': []}) as spy, patch(
        'game.services.story_service.MongoService.get_conversation_history', return_value=[]
    ):
        StoryService(ai=ai).play_turn(session=chaptered_session, user_input='look around')
    assert 'Chapter 2 - CHAPTER II' in spy.call_args.kwargs['chapter_context']


def test_next_chapter_event_advances_session_and_stops_at_last_chapter(chaptered_session):
    ai = OfflineNarrator()
    with patch.object(ai, 'generate_story_turn', return_value={'narrative': 'On we go.', 'events': [{'type': 'next_chapter'}]}), patch(
        'game.services.story_service.MongoService.get_conversation_history', return_value=[]
    ):
        service = StoryService(ai=ai)
        result = service.play_turn(session=chaptered_session, user_input='continue')
        assert result.notes == ['The story moves on to chapter 3.']
        assert result.state['chapter'] == 3
        again = service.play_turn(session=chaptered_session, user_input='continue')
    assert again.notes == []
    assert StorySession.objects.get(id=chaptered_session.id).current_chapter == 3


# --- chapter picker ---------------------------------------------------------------


def _prepare(api):
    for _ in range(5):
        resp = api.post('/api/play/prepare/', {'book': 'mines.txt', 'batch': 10}, format='json').json()
        if resp.get('ready'):
            return resp
    raise AssertionError(f'book never became ready: {resp}')


def test_play_chapters_lists_titles_and_digests(api, books_dir, offline_llm):
    _prepare(api)
    resp = api.get('/api/play/chapters/', {'book': 'mines.txt'})
    assert resp.status_code == 200
    data = resp.json()
    assert data['chapter_count'] == 3 and data['done'] == 3
    assert [c['index'] for c in data['chapters']] == [1, 2, 3]
    assert data['chapters'][0]['title'] == 'CHAPTER I'
    assert set(data['chapters'][0]) == {'book_key', 'index', 'title', 'summary', 'locations', 'characters', 'events'}
    assert data['chapters'][0]['summary']
    assert api.get('/api/play/chapters/', {'book': 'nope.txt'}).status_code == 404


def test_play_start_from_a_later_chapter_sets_chapter_and_location(api, books_dir, offline_llm):
    _prepare(api)
    book = Book.objects.get(title='mines')
    world = World.objects.get(book=book)
    world.locations = ['Durban', 'Kukuanaland', 'Solomon\'s Mines']
    world.save(update_fields=['locations'])
    MongoService.save_chapter_summary(
        book_id=book.store_key,
        index=3,
        summary={'summary': 'They reach the mines.', 'characters': [{'name': 'Gagool', 'role': 'witch', 'status': 'alive'}],
                 'locations': ["solomon's mines", 'Place of Death'], 'items': [], 'events': [], 'hooks': []},
    )

    resp = api.post('/api/play/start/', {'book': 'mines.txt', 'name': 'Allan', 'start_chapter': 3}, format='json')
    assert resp.status_code == 201
    body = resp.json()
    assert body['state']['chapter'] == 3
    assert body['state']['location'] == "Solomon's Mines"  # matched against the world's locations, case-insensitively
    assert body['chapter']['index'] == 3 and body['chapter']['summary'] == 'They reach the mines.'
    assert body['chapter']['characters'] == ['Gagool']
    assert StorySession.objects.get(id=body['session']['id']).current_chapter == 3

    # Past the last chapter: clamped. Chapter whose summary names no known place: first named place.
    resp = api.post('/api/play/start/', {'book': 'mines.txt', 'name': 'Allan', 'start_chapter': 99}, format='json')
    assert resp.json()['state']['chapter'] == 3
    MongoService.save_chapter_summary(
        book_id=book.store_key, index=2,
        summary={'summary': 'Desert.', 'characters': [], 'locations': ['The Desert'], 'items': [], 'events': [], 'hooks': []},
    )
    resp = api.post('/api/play/start/', {'book': 'mines.txt', 'name': 'Allan', 'start_chapter': 2}, format='json')
    assert resp.json()['state']['location'] == 'The Desert'
    # No start_chapter: chapter 1 at the world's first location, as before.
    resp = api.post('/api/play/start/', {'book': 'mines.txt', 'name': 'Allan'}, format='json')
    assert resp.json()['state']['chapter'] == 1 and resp.json()['state']['location'] == 'Durban'


def test_prepare_rebuilds_summaries_lost_from_the_memory_store(api, books_dir, offline_llm):
    _prepare(api)
    world_id = World.objects.get(book__title='mines').id
    MongoService._memory_chapters.clear()  # what a server restart does without MONGODB_URI

    first = api.post('/api/play/prepare/', {'book': 'mines.txt', 'batch': 2}, format='json').json()
    assert first['ready'] is False and first['total'] == 3 and first['done'] == 2
    with patch('game.views.build_world_from_book') as build:
        second = api.post('/api/play/prepare/', {'book': 'mines.txt', 'batch': 2}, format='json').json()
    assert second['ready'] is True and second['world_id'] == world_id and second['done'] == 3
    build.assert_not_called()  # the existing world is reused; only the summaries were rebuilt
    assert len(api.get('/api/play/chapters/', {'book': 'mines.txt'}).json()['chapters']) == 3


# --- export / import --------------------------------------------------------------


def test_chapters_export_and_import_round_trip(books_dir, offline_llm, tmp_path, settings):
    from django.core.management import call_command

    book = Book.objects.create(title='mines', content=THREE_CHAPTERS, source_type='local')
    prepare_book(book, OfflineNarrator())
    before = MongoService.get_chapter_summaries(book_id=book.store_key)
    assert len(before) == 3

    out = tmp_path / 'backup' / 'mines.json'
    call_command('chapters_export', 'mines', out=str(out))
    assert out.is_file()

    # Simulate the store being wiped (restart without MongoDB, or a new database).
    MongoService._memory_chapters.clear()
    assert MongoService.chapter_progress(book_id=book.store_key)['total'] == 0
    call_command('chapters_import', str(out))
    assert MongoService.get_chapter_summaries(book_id=book.store_key) == before
    assert MongoService.chapter_progress(book_id=book.store_key) == {'total': 3, 'done': 3, 'failed': 0, 'pending': 0}

    # A fresh database: the Book row is recreated from BOOKS_DIR and the chapters attach to it.
    Book.objects.all().delete()
    MongoService._memory_chapters.clear()
    call_command('chapters_import', str(out))
    new_book = Book.objects.get(title='mines')
    assert new_book.chapter_count == 3
    assert [c['index'] for c in MongoService.get_chapter_summaries(book_id=new_book.store_key)] == [1, 2, 3]


def test_ingest_groups_short_chapters_per_setting(settings):
    settings.CHAPTER_GROUP_CHARS = 2000
    book = Book.objects.create(title='grouped', content=THREE_CHAPTERS)  # three ~550-char chapters
    assert ingest_book(book)['total'] == 1
    assert book.chapter_count == 1
    settings.CHAPTER_GROUP_CHARS = 0
    other = Book.objects.create(title='plain', content=THREE_CHAPTERS)
    assert ingest_book(other)['total'] == 3
