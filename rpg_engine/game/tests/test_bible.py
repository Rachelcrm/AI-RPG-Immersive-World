"""The story bible: hard facts extracted per chapter, merged by code, profiled once per character."""
import json
from unittest.mock import patch

import pytest
from django.core.management import call_command

from game.models import Book, Character, NPC, StorySession, World
from game.services import bible
from game.services.llm_service import LLMService
from game.services.mongo_service import MongoService
from game.services.offline_narrator import OfflineNarrator
from game.services.story_service import StoryService
from game.services.world_builder import build_world_from_book, prepare_book

pytestmark = pytest.mark.django_db


# --- schema -------------------------------------------------------------------------


def test_normalize_chapter_bible_enforces_the_schema():
    raw = {
        'characters': [
            {
                'name': ' 齐夏 ',
                'aliases': ['齐夏', '夏哥'],
                'identity': '主角',
                'importance': 'MAJOR',
                'status': '活着',
                'quotes': ['“闭嘴。”', '闭嘴。', 'x' * 100, '', '好。', '走。', '多余的第五句'],
                'reactions': [{'situation': '被质问', 'action': '沉默'}, '转身离开', {'situation': 'no action'}],
                'relations': [{'target': '贺今朝', 'relation': '对手'}, {'target': '', 'relation': '无'}],
            },
            'string name',
            {'identity': 'nameless'},
        ],
        'events': [
            {'description': '抽牌', 'type': 'game', 'participants': ['齐夏'], 'consequence': '成为说谎者'},
            {'description': '???', 'type': 'bogus'},
            'plain string beat',
        ],
        'facts': [{'content': '十天内集齐三千六百个道', 'category': 'rule'}, {'content': '规则二', 'category': 'nope'}, 'rule three'],
    }
    out = bible.normalize_chapter_bible(raw, chapter_index=3)
    qi = out['characters'][0]
    assert qi['name'] == '齐夏' and qi['aliases'] == ['夏哥']  # alias equal to the name is dropped
    assert qi['importance'] == 'major'
    assert qi['quotes'] == ['闭嘴。', 'x' * bible.MAX_QUOTE_CHARS, '好。', '走。']  # quote marks stripped, deduped, capped
    assert qi['reactions'] == [{'situation': '被质问', 'action': '沉默'}, {'situation': '', 'action': '转身离开'}]
    assert qi['relations'] == [{'target': '贺今朝', 'relation': '对手'}]
    assert out['characters'][1] == {
        'name': 'string name', 'aliases': [], 'identity': '', 'importance': 'minor', 'status': '', 'quotes': [], 'reactions': [], 'relations': [],
    }
    assert len(out['characters']) == 2
    assert [b['type'] for b in out['beats']] == ['game', 'other', 'other']
    assert out['beats'][0] == {
        'chapter': 3, 'order': 1, 'description': '抽牌', 'type': 'game', 'participants': ['齐夏'], 'consequence': '成为说谎者',
    }
    assert [f['category'] for f in out['facts']] == ['rule', 'world', 'world']
    assert out['facts'][2]['content'] == 'rule three' and out['facts'][2]['chapter'] == 3


def test_normalize_profile_keeps_one_side_of_each_pair():
    profile = bible.normalize_profile(
        {'personality': 'p', 'speech_style': 's', 'style_tags': ['terse', 'talkative', 'calm', 'loud', 'CALM'], 'behaviour': ['b1']},
        signature='sig',
    )
    assert profile == {'personality': 'p', 'speech_style': 's', 'style_tags': ['calm'], 'behaviour': ['b1'], 'signature': 'sig'}


# --- merging ------------------------------------------------------------------------


def _chapter(index, characters=(), beats=(), facts=()):
    return {
        'index': index,
        'title': f'ch{index}',
        'summary': {
            'summary': '',
            'bible': {
                'characters': [
                    {'name': c[0], 'aliases': list(c[1]), 'identity': c[2], 'importance': c[3], 'status': c[4],
                     'quotes': list(c[5]), 'reactions': [], 'relations': []}
                    for c in characters
                ],
                'beats': [{'chapter': index, 'order': i + 1, 'description': d, 'type': 'other', 'participants': [], 'consequence': ''} for i, d in enumerate(beats)],
                'facts': [{'chapter': index, 'content': f, 'category': 'rule'} for f in facts],
            },
        },
    }


def test_merge_bible_joins_aliases_sorts_evidence_and_dedupes():
    chapters = [
        _chapter(2, [('李明', [], '说谎者', 'minor', '化名', ['我叫李明'])], beats=['b2'], facts=['规则A']),
        _chapter(1, [('齐夏', [], '主角', 'minor', '入场', ['你好']), ('路人', [], '', 'minor', '', [])], beats=['b1a', 'b1b'], facts=['规则A', '规则B']),
        _chapter(3, [('齐夏', ['李明'], '主角', 'major', '胜出', ['结束了'])], beats=['b3'], facts=['规则 A']),
        {'index': 4, 'title': 'no bible', 'summary': {'summary': 'old style'}},
    ]
    merged = bible.merge_bible(chapters)
    names = [c['name'] for c in merged['characters']]
    assert names == ['齐夏', '路人']  # 李明 folded into 齐夏 via the alias, major first
    qi = merged['characters'][0]
    assert qi['aliases'] == ['李明']
    assert qi['importance'] == 'major' and qi['chapters'] == [1, 2, 3]
    assert [q['chapter'] for q in qi['quotes']] == [1, 2, 3]
    assert [t['status'] for t in qi['timeline']] == ['入场', '化名', '胜出']
    assert qi['profile'] is None
    assert [(b['sequence'], b['chapter'], b['description']) for b in merged['plot']] == [(1, 1, 'b1a'), (2, 1, 'b1b'), (3, 2, 'b2'), (4, 3, 'b3')]
    assert [(f['chapter'], f['content']) for f in merged['facts']] == [(1, '规则A'), (1, '规则B')]  # '规则 A' == '规则A'


def test_narrator_context_hides_later_chapters_and_absent_characters():
    characters = [
        {'name': '齐夏', 'aliases': [], 'identity': '主角', 'importance': 'major', 'first_chapter': 1, 'chapters': [1, 2, 3],
         'quotes': [{'chapter': 1, 'text': '早安'}, {'chapter': 3, 'text': '晚了'}],
         'reactions': [{'chapter': 3, 'situation': '被骂', 'action': '沉默'}], 'relations': [], 'timeline': [{'chapter': 3, 'status': '死亡'}],
         'profile': {'personality': '冷静', 'speech_style': '话少', 'style_tags': ['terse'], 'behaviour': ['沉默应对'], 'signature': 's'}},
        {'name': '贺今朝', 'aliases': [], 'identity': '对手', 'importance': 'major', 'first_chapter': 1, 'chapters': [1],
         'quotes': [], 'reactions': [], 'relations': [], 'timeline': [], 'profile': None},
        {'name': '后来者', 'aliases': [], 'identity': '', 'importance': 'major', 'first_chapter': 5, 'chapters': [5],
         'quotes': [], 'reactions': [], 'relations': [], 'timeline': [], 'profile': None},
    ]
    plot = [{'sequence': 1, 'chapter': 2, 'order': 1, 'type': 'game', 'description': '抽牌', 'participants': [], 'consequence': '定角色'}]
    facts = [{'chapter': 1, 'category': 'rule', 'content': '规则一'}, {'chapter': 4, 'category': 'rule', 'content': '剧透规则'}]
    text = bible.narrator_context(characters=characters, plot=plot, facts=facts, chapter=2, present=['齐夏', '后来者'])
    assert '早安' in text and '晚了' not in text and '死亡' not in text and '沉默' in text  # behaviour rule, not the ch3 reaction
    assert '[game] 抽牌 -> 定角色' in text
    assert '规则一' in text and '剧透规则' not in text
    assert '贺今朝' not in text  # not present this turn
    assert '后来者' not in text  # first appears later in the book


# --- model layer -------------------------------------------------------------------


class _Scripted(LLMService):
    provider = 'scripted'
    key_setting = 'X'

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    @property
    def model(self):
        return 'scripted'

    def is_configured(self):
        return True

    def _complete(self, prompt, *, max_tokens):
        self.prompts.append((prompt, max_tokens))
        return self.reply


def test_summarize_chapter_stores_evidence_beside_the_prose_summary():
    reply = json.dumps({
        'summary': '齐夏进入游戏。',
        'characters': [{'name': '齐夏', 'identity': '主角', 'importance': 'major', 'status': '存活', 'quotes': ['“我不说。”'],
                        'reactions': [{'situation': '被逼问', 'action': '保持沉默'}], 'relations': []}],
        'locations': ['终焉之地'], 'items': ['说谎者牌'],
        'events': [{'description': '抽到说谎者牌', 'type': 'game', 'participants': ['齐夏'], 'consequence': ''}],
        'facts': [{'content': '全员投中则说谎者死', 'category': 'rule'}],
        'hooks': ['找出说谎者'],
    })
    ai = _Scripted(reply)
    out = ai.summarize_chapter(book_title='十日终焉', chapter_index=2, chapter_count=5, chapter_title='第二章', text='正文')
    assert out['characters'] == [{'name': '齐夏', 'role': '主角', 'status': '存活'}]
    assert out['events'] == ['抽到说谎者牌']
    assert out['bible']['characters'][0]['quotes'] == ['我不说。']
    assert out['bible']['facts'] == [{'chapter': 2, 'content': '全员投中则说谎者死', 'category': 'rule'}]
    prompt, max_tokens = ai.prompts[0]
    assert 'verbatim' in prompt and 'reactions' in prompt and max_tokens >= 4000


def test_profile_character_uses_the_evidence_and_normalises():
    ai = _Scripted(json.dumps({'personality': '寡言。', 'speech_style': '短句。', 'style_tags': ['terse', 'bogus'], 'behaviour': ['沉默']}))
    character = {'name': '齐夏', 'aliases': ['李明'], 'identity': '主角', 'chapters': [1, 2],
                 'quotes': [{'chapter': 1, 'text': '我不说。'}], 'reactions': [{'chapter': 2, 'situation': '被问', 'action': '沉默'}],
                 'timeline': [{'chapter': 2, 'status': '化名李明'}], 'relations': []}
    profile = ai.profile_character(book_title='十日终焉', character=character)
    assert profile['style_tags'] == ['terse'] and profile['signature'] == bible.evidence_signature(character)
    prompt = ai.prompts[0][0]
    assert '我不说。' in prompt and '被问 -> 沉默' in prompt and '化名李明' in prompt and 'aka 李明' in prompt


# --- pipeline ------------------------------------------------------------------------

PARA = 'Allan Quatermain met Sir Henry Curtis aboard the ship. "We sail at dawn," said Allan Quatermain. ' * 8
BOOK = f'CHAPTER I\n{PARA}\n\nCHAPTER II\n{PARA}\n\nCHAPTER III\n{PARA}'


@pytest.fixture(autouse=True)
def no_grouping(settings):
    settings.CHAPTER_GROUP_CHARS = 0


def test_prepare_builds_bible_profiles_majors_and_seeds_npcs_from_the_book():
    book = Book.objects.create(title='mines', content=BOOK)
    ai = OfflineNarrator()
    with patch.object(ai, 'profile_character', wraps=ai.profile_character) as spy:
        prepare_book(book, ai)
    characters = MongoService.get_characters(book_id=book.store_key)
    assert characters[0]['name'] == 'Allan Quatermain' and characters[0]['importance'] == 'major'
    assert characters[0]['chapters'] == [1, 2, 3]
    assert characters[0]['quotes'][0] == {'chapter': 1, 'text': 'We sail at dawn,'}
    assert characters[0]['profile']['style_tags'] == ['terse', 'calm']
    assert spy.call_count == len([c for c in characters if c['importance'] == 'major'])
    assert len(MongoService.get_plot(book_id=book.store_key)) == 3
    assert MongoService.bible_meta(book_id=book.store_key)['done_chapters'] == 3

    # Nothing changed: no new profile calls.
    with patch.object(ai, 'profile_character', wraps=ai.profile_character) as spy:
        prepare_book(book, ai)
    assert spy.call_count == 0

    world = build_world_from_book(book, ai)
    npc = NPC.objects.get(world=world, name='Allan Quatermain')
    assert npc.role == 'figure' and 'Speaks briefly' in npc.description
    assert NPC.objects.filter(world=world).count() == len([c for c in characters if c['importance'] == 'major'])

    character = Character.objects.create(world=world, name='Kai', current_location=npc.location)
    session = StorySession.objects.create(world=world, character=character, title='t', current_chapter=1)
    context = StoryService.chapter_context(session)
    assert 'Character bible' in context and 'We sail at dawn' in context and 'Speaks briefly' in context
    assert 'Key beats of the current chapter' in context and 'Chapter 1 (CHAPTER I) unfolds.' in context


def test_profile_failures_are_recorded_once_and_not_retried_every_poll():
    book = Book.objects.create(title='mines', content=BOOK)
    ai = OfflineNarrator()
    with patch.object(ai, 'profile_character', side_effect=RuntimeError('model down')) as spy:
        prepare_book(book, ai)
        prepare_book(book, ai)
    majors = MongoService.get_characters(book_id=book.store_key, importance='major')
    assert spy.call_count == len(majors)
    assert all(c['profile']['error'] == 'model down' for c in majors)


def test_export_import_round_trip_keeps_profiles_and_reset_drops_everything(tmp_path):
    book = Book.objects.create(title='mines', content=BOOK, source_type='local')
    prepare_book(book, OfflineNarrator())
    before = MongoService.get_characters(book_id=book.store_key)
    out = tmp_path / 'mines.json'
    call_command('chapters_export', 'mines', out=str(out))
    payload = json.loads(out.read_text(encoding='utf-8'))
    assert payload['bible']['characters'][0]['profile']['personality']

    MongoService._memory_chapters.clear()
    MongoService._memory_bible.clear()
    call_command('chapters_import', str(out))
    assert MongoService.get_characters(book_id=book.store_key) == before
    assert MongoService.get_plot(book_id=book.store_key)

    call_command('chapters_reset', 'mines')
    assert MongoService.chapter_progress(book_id=book.store_key) == {'total': 3, 'done': 0, 'failed': 0, 'pending': 3}
    assert MongoService.get_characters(book_id=book.store_key) == []
    assert MongoService.bible_meta(book_id=book.store_key) is None


def test_bible_show_prints_characters(capsys):
    book = Book.objects.create(title='mines', content=BOOK)
    prepare_book(book, OfflineNarrator())
    call_command('bible_show', 'mines', plot=True, facts=True)
    out = capsys.readouterr().out
    assert '* Allan Quatermain' in out and 'Plot:' in out and 'Facts:' in out
    call_command('bible_show', 'mines', character='allan quatermain')
    assert '"speech_style"' in capsys.readouterr().out


def test_play_prepare_reports_profile_step(api, settings, tmp_path):
    (tmp_path / 'mines.txt').write_text(BOOK, encoding='utf-8')
    settings.BOOKS_DIR = tmp_path
    with patch('game.views.get_llm_service', return_value=OfflineNarrator()):
        first = api.post('/api/play/prepare/', {'book': 'mines.txt', 'batch': 3}, format='json').json()
        assert first['ready'] is True and first['profiles_pending'] == 0
        assert NPC.objects.filter(world_id=first['world_id'], name='Allan Quatermain').exists()
        # Profiles are written a few per request; the world waits for them.
        MongoService._memory_bible.clear()
        with patch('game.views.ensure_bible', return_value=2):
            again = api.post('/api/play/prepare/', {'book': 'mines.txt'}, format='json').json()
    assert again['ready'] is False and again['profiles_pending'] == 2 and again['pending'] == 0


def test_objective_hint_is_carried_on_the_session_and_returned_by_the_api(api):
    book = Book.objects.create(title='mines', content=BOOK)
    ai = OfflineNarrator()
    prepare_book(book, ai)
    world = build_world_from_book(book, ai)
    character = Character.objects.create(world=world, name='Kai', current_location=world.locations[0])
    session = StorySession.objects.create(world=world, character=character, title='t', objective='find the ship')

    scripted = _Scripted(json.dumps({'narrative': 'Waves.', 'events': [], 'objective': 'we are trying to board the ship'}))
    with patch('game.services.story_service.get_llm_service', return_value=scripted):
        resp = api.post(f'/api/sessions/{session.id}/interact/', {'user_input': 'look'}, format='json')
    assert resp.status_code == 200
    assert resp.json()['objective'] == 'we are trying to board the ship'
    assert 'Current objective shown to the player: find the ship' in scripted.prompts[0][0]
    session.refresh_from_db()
    assert session.objective == 'we are trying to board the ship'
    assert api.get(f'/api/sessions/{session.id}/').json()['session']['objective'] == 'we are trying to board the ship'

    # A reply without an objective keeps the previous one.
    scripted.reply = json.dumps({'narrative': 'Still waves.', 'events': []})
    with patch('game.services.story_service.get_llm_service', return_value=scripted):
        assert api.post(f'/api/sessions/{session.id}/interact/', {'user_input': 'wait'}, format='json').json()['objective'] == 'we are trying to board the ship'
