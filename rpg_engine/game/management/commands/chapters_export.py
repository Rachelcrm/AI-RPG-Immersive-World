"""Save a book's chapter summaries to JSON so they never have to be paid for twice.

    python manage.py chapters_export "king_solomons_mines" --out backups/king_solomons_mines.json

The book is matched by id or title. The file holds every chapter document (text, status and
summary) and the story bible (characters with their profiles, plot beats, facts); restore it
with `chapters_import`.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from game.models import Book
from game.services.mongo_service import MongoService


def find_book(ref: str) -> Book:
    book = Book.objects.filter(id=ref).first() if ref.isdigit() else None
    if book is None:
        book = Book.objects.filter(title=ref).order_by('-id').first()
    if book is None:
        raise CommandError(f'No book with id or title {ref!r}.')
    return book


class Command(BaseCommand):
    help = "Export a book's chapter summaries to a JSON file."

    def add_arguments(self, parser):
        parser.add_argument('book', help='Book id or title')
        parser.add_argument('--out', help='Output path (default: <title>.chapters.json)')

    def handle(self, *args, **options):
        book = find_book(options['book'])
        docs = MongoService.export_chapters(book_id=book.store_key)
        if not docs:
            raise CommandError(f'Book {book.id} "{book.title}" has no chapters in the store (nothing to export).')
        out = Path(options['out'] or f'{book.title}.chapters.json')
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'book_title': book.title,
            'source_type': book.source_type,
            'chapter_count': book.chapter_count,
            'chapters': docs,
            'bible': MongoService.export_bible(book_id=book.store_key),
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
        done = sum(1 for d in docs if d.get('status') == 'done')
        self.stdout.write(
            f'Wrote {len(docs)} chapters ({done} summarised) and {len(payload["bible"]["characters"])} characters '
            f'of "{book.title}" to {out}'
        )
