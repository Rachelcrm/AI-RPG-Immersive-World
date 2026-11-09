from unittest.mock import patch

import pytest

from game.models import StorySession, World

pytestmark = pytest.mark.django_db

FAKE_WORLD = {
    'world_name': 'Saltmere',
    'lore_summary': 'A harbor town.',
    'factions': ['Lamplighters'],
    'locations': ['Drowned Bell Tower', 'Kelp Moors'],
    'main_conflict': 'The lantern went out.',
}


@pytest.fixture
def books_dir(settings, tmp_path):
    (tmp_path / 'lantern.txt').write_text('Once there was a lantern.', encoding='utf-8')
    (tmp_path / 'notes.md').write_text('not a book', encoding='utf-8')
    settings.BOOKS_DIR = tmp_path
    return tmp_path


def test_play_page_renders(api):
    resp = api.get('/')
    assert resp.status_code == 200
    assert b'/api/play/start/' in resp.content


def test_local_books_lists_only_txt(api, books_dir):
    resp = api.get('/api/books/local/')
    assert resp.status_code == 200
    assert resp.json()['books'] == [{'file': 'lantern.txt', 'title': 'lantern'}]


def test_play_start_builds_world_once_and_reuses_it(api, books_dir):
    fake_chapter = {'summary': 'A lantern.', 'characters': [], 'locations': [], 'items': [], 'events': [], 'hooks': []}
    with patch('game.services.llm_service.LLMService.generate_world', return_value=FAKE_WORLD) as gen, patch(
        'game.services.llm_service.LLMService.summarize_chapter', return_value=fake_chapter
    ) as summarize, patch(
        'game.services.llm_service.LLMService.generate_components', side_effect=ValueError('no key')
    ), patch('game.services.llm_service.LLMService.generate_market_candidates', side_effect=ValueError('no key')):
        first = api.post('/api/play/start/', {'book': 'lantern.txt', 'name': 'Ilsa', 'role': 'Lamplighter'}, format='json')
        second = api.post('/api/play/start/', {'book': 'lantern.txt', 'name': 'Tam'}, format='json')

    assert first.status_code == 201
    assert first.json()['book_title'] == 'lantern'
    assert first.json()['world']['name'] == 'Saltmere'
    assert first.json()['state']['location'] == 'Drowned Bell Tower'
    assert second.status_code == 201
    assert gen.call_count == 1
    assert summarize.call_count == 1  # one tiny chapter, summarised once
    assert gen.call_args.kwargs['chapter_summaries'][0]['summary'] == fake_chapter
    assert World.objects.count() == 1
    assert StorySession.objects.filter(world__source_book_title='lantern').count() == 2


def test_play_start_rejects_unknown_or_escaping_paths(api, books_dir):
    for name in ['missing.txt', 'notes.md', '../.env']:
        resp = api.post('/api/play/start/', {'book': name}, format='json')
        assert resp.status_code == 404, name


def test_play_start_returns_502_when_generation_fails(api, books_dir):
    with patch('game.services.llm_service.LLMService.generate_world', side_effect=ValueError('no key')), patch(
        'game.services.llm_service.LLMService.summarize_chapter', side_effect=ValueError('no key')
    ):
        resp = api.post('/api/play/start/', {'book': 'lantern.txt'}, format='json')
    assert resp.status_code == 502
    assert World.objects.count() == 0
