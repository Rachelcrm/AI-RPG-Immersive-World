from game.services.chapters import MAX_CHARS, split_chapters

PARA = 'The travellers pressed on through the dust. ' * 12  # ~540 chars, above MIN_CHARS


def test_splits_on_english_headings_and_strips_gutenberg_boilerplate():
    text = (
        'The Project Gutenberg eBook of Example\n*** START OF THE PROJECT GUTENBERG EBOOK EXAMPLE ***\n'
        'CONTENTS\nCHAPTER I\nCHAPTER II\nCHAPTER III\n\n'
        'CHAPTER I\nI MEET SIR HENRY CURTIS\n' + PARA + '\n\n'
        'CHAPTER II\nTHE LEGEND\n' + PARA + '\n\n'
        'Chapter 3: The Desert\n' + PARA + '\n\n'
        '*** END OF THE PROJECT GUTENBERG EBOOK EXAMPLE ***\nLicense text here.'
    )
    chapters = split_chapters(text)
    assert [c.index for c in chapters] == [1, 2, 3]
    assert chapters[0].title == 'CHAPTER I'
    assert chapters[2].title == 'Chapter 3: The Desert'
    assert 'CONTENTS' in chapters[0].text  # the table of contents folds into the first real chapter
    assert 'License text' not in chapters[-1].text
    assert all('Project Gutenberg' not in c.text for c in chapters)


def test_splits_on_chinese_headings():
    body = '包公升堂问案，左右衙役肃立。' * 40
    text = f'第一回 包公出世\n{body}\n第二回 审乌盆\n{body}\n第十三章 结案\n{body}'
    chapters = split_chapters(text)
    assert [c.title for c in chapters] == ['第一回 包公出世', '第二回 审乌盆', '第十三章 结案']
    assert chapters[1].text.startswith('包公升堂')


def test_falls_back_to_fixed_chunks_without_headings():
    text = '\n\n'.join(PARA for _ in range(120))  # ~65k chars, no headings
    chapters = split_chapters(text)
    assert len(chapters) >= 3
    assert all(len(c.text) <= MAX_CHARS for c in chapters)
    assert chapters[0].title == 'Section (part 1)'
    assert ''.join(c.text for c in chapters).count('travellers') == text.count('travellers')


def test_long_chapter_is_split_into_parts():
    long_body = '\n\n'.join(PARA for _ in range(60))  # ~32k chars
    text = f'CHAPTER I\n{PARA}\n\nCHAPTER II\n{long_body}'
    chapters = split_chapters(text)
    titles = [c.title for c in chapters]
    assert titles[0] == 'CHAPTER I'
    assert titles[1:] == ['CHAPTER II (part 1)', 'CHAPTER II (part 2)']


def test_short_or_empty_text():
    assert split_chapters('') == []
    assert [c.title for c in split_chapters('Just a note.')] == ['Section']


def test_bracketed_chinese_headings_ignore_prose_that_starts_with_di():
    body = '　　齐夏环顾四周。\n\n　　第三回合，齐夏出了「石头」，而对方依然是「布」。\n\n' + '山羊头笑了。' * 120
    text = (
        '书名：十日终焉\n章节：共 1496 章\n\n【内容简介】\n一段简介。\n\n'
        f'【第一章空屋】\n{body}\n\n【第二章说谎】\n{body}\n\n【第三章不破，不立】\n{body}'
    )
    chapters = split_chapters(text)
    assert [c.title for c in chapters] == ['第一章空屋', '第二章说谎', '第三章不破，不立']
    assert '书名：十日终焉' in chapters[0].text  # the short preface folds into chapter 1
    assert '第三回合' in chapters[1].text  # not treated as a heading


def test_short_chapters_are_grouped_but_long_ones_are_not():
    short = '夜色渐深。' * 100  # 500 chars
    text = '\n'.join(f'第{n}章 标题{n}\n{short}' for n in range(1, 11))
    grouped = split_chapters(text, group_chars=2200)  # four chapters (~2050 chars) fit, five do not
    assert [c.title for c in grouped] == ['第1章 标题1 – 第4章 标题4', '第5章 标题5 – 第8章 标题8', '第9章 标题9 – 第10章 标题10']
    assert grouped[0].text.count('第') == 4 and '第4章 标题4' in grouped[0].text
    assert all(len(c.text) <= 2200 for c in grouped)
    ungrouped = split_chapters(text, group_chars=0)
    assert len(ungrouped) == 10

    long_body = 'The travellers pressed on. ' * 500  # ~13k chars, above the default GROUP_CHARS
    long_text = '\n'.join(f'CHAPTER {r}\n{long_body}' for r in ['I', 'II', 'III'])
    assert [c.title for c in split_chapters(long_text, group_chars=12000)] == ['CHAPTER I', 'CHAPTER II', 'CHAPTER III']
