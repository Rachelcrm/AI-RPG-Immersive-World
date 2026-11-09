"""Split a book's text into chapters for per-chapter summarisation.

Headings are detected for English ("CHAPTER IV", "Chapter 4: ...") and
Chinese ("第四章", "第十回", "【第四章 标题】") books. Books without usable
headings fall back to fixed-size chunks. Every chapter is kept under MAX_CHARS so
one chapter fits comfortably in a single summarisation prompt, and runs of short
chapters (web novels: 1000+ chapters of ~2000 characters) are grouped into units
of about GROUP_CHARS so the number of summaries stays manageable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CHARS = 25000  # longer chapters are split into parts (~6k tokens of English, ~30k of Chinese)
MIN_CHARS = 400  # shorter "chapters" (table-of-contents lines, epigraphs) merge into a neighbour
GROUP_CHARS = 12000  # default for settings.CHAPTER_GROUP_CHARS; 0 disables grouping

_HEADING = re.compile(
    r'^[ \t]*[【\[]?(?:'
    r'(?:CHAPTER|Chapter|BOOK|Book|PART|Part)[ \t]+(?:[IVXLC]+|\d+|[A-Za-z-]+)\b[^\n]{0,80}'
    # A Chinese heading is short and never ends a sentence: "第三回合，他出了石头。" is prose.
    r'|第[零〇一二三四五六七八九十百千两\d]+[章回节卷集][^\n。；：]{0,40}'
    r')[ \t]*$',
    re.MULTILINE,
)
_GUTENBERG_START = re.compile(r'\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\*\*\*', re.IGNORECASE)
_GUTENBERG_END = re.compile(r'\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK', re.IGNORECASE)


@dataclass
class Chapter:
    index: int  # 1-based
    title: str
    text: str


def strip_boilerplate(text: str) -> str:
    """Drop the Project Gutenberg licence header/footer when present."""
    start = _GUTENBERG_START.search(text)
    if start:
        text = text[start.end():]
    end = _GUTENBERG_END.search(text)
    if end:
        text = text[: end.start()]
    return text.strip()


def split_chapters(text: str, *, group_chars: int = 0) -> list[Chapter]:
    """Chapters of `text`; with `group_chars` > 0, runs of short chapters are grouped (see _group_short)."""
    text = strip_boilerplate(text.replace('\r\n', '\n'))
    if not text:
        return []
    sections = _split_on_headings(text)
    if len(sections) < 2:
        sections = [('', text)]
    sections = _group_short(_merge_short(sections), group_chars)
    chapters: list[Chapter] = []
    for title, body in sections:
        for part_no, part in enumerate(_chunk(body), start=1):
            label = title or 'Section'
            if part_no > 1 or (len(body) > MAX_CHARS):
                label = f'{label} (part {part_no})'
            chapters.append(Chapter(index=len(chapters) + 1, title=label, text=part))
    return chapters


def _split_on_headings(text: str) -> list[tuple[str, str]]:
    matches = list(_HEADING.finditer(text))
    if not matches:
        return []
    sections: list[tuple[str, str]] = []
    preface = text[: matches[0].start()].strip()
    if preface:
        sections.append(('Preface', preface))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        title = ' '.join(m.group(0).split()).strip('【】[]')
        sections.append((title, body))
    return sections


def _merge_short(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Fold tiny sections (TOC entries, blank headings) into the following section."""
    merged: list[tuple[str, str]] = []
    carry_title, carry_text = '', ''
    for title, body in sections:
        if carry_text:
            # The substantive section keeps its own title; the stub text rides along at the top.
            body = f'{carry_text}\n\n{title}\n{body}'.strip() if body else carry_text
            carry_title, carry_text = '', ''
        if len(body) < MIN_CHARS:
            carry_title, carry_text = title, (f'{title}\n{body}'.strip() if title else body)
            continue
        merged.append((title, body))
    if carry_text:
        if merged:
            title, body = merged[-1]
            merged[-1] = (title, f'{body}\n\n{carry_text}')
        else:
            merged.append((carry_title or 'Section', carry_text))
    return merged


def _group_short(sections: list[tuple[str, str]], group_chars: int) -> list[tuple[str, str]]:
    """Join runs of consecutive short chapters into units of up to `group_chars`.

    A unit keeps every heading inside its text and is titled "first – last". Chapters already
    longer than the limit are left alone, so a classic novel with long chapters is unchanged.
    """
    if group_chars <= 0:
        return sections
    grouped: list[tuple[str, str]] = []
    run: list[tuple[str, str]] = []
    run_len = 0

    def flush() -> None:
        if not run:
            return
        if len(run) == 1:
            grouped.append(run[0])
        else:
            title = f'{run[0][0]} – {run[-1][0]}'
            grouped.append((title, '\n\n'.join(f'{t}\n{b}' if t else b for t, b in run)))

    for title, body in sections:
        size = len(title) + len(body) + 2
        if run and run_len + size > group_chars:
            flush()
            run, run_len = [], 0
        run.append((title, body))
        run_len += size
    flush()
    return grouped


def _chunk(body: str) -> list[str]:
    """Split on paragraph boundaries so no piece exceeds MAX_CHARS."""
    if len(body) <= MAX_CHARS:
        return [body]
    pieces, current = [], ''
    for para in re.split(r'\n\s*\n', body):
        para = para.strip()
        if not para:
            continue
        while len(para) > MAX_CHARS:  # a single giant paragraph: hard cut
            if current:
                pieces.append(current)
                current = ''
            pieces.append(para[:MAX_CHARS])
            para = para[MAX_CHARS:]
        if current and len(current) + len(para) + 2 > MAX_CHARS:
            pieces.append(current)
            current = para
        else:
            current = f'{current}\n\n{para}' if current else para
    if current:
        pieces.append(current)
    return pieces
