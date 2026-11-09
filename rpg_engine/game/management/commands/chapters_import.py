"""Restore chapter summaries saved by `chapters_export`.

    python manage.py chapters_import backups/king_solomons_mines.json
    python manage.py chapters_import backups/king_solomons_mines.json --book 7

Without --book the Book row is matched by the title stored in the file, and created (from the
.txt in BOOKS_DIR with that name) if there is none. Existing chapters of that book are replaced.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from game.models import Book
from game.services.mongo_service import MongoService
from game.services.world_builder import LOCAL_SOURCE, rebuild_bible

from .chapters_export import find_book


class Command(BaseCommand):
    help = "Import a book's chapter summaries from a JSON file written by chapters_export."

    def add_arguments(self, parser):
        parser.add_argument('path', help='JSON file written by chapters_export')
        parser.add_argument('--book', help='Book id or title to attach the chapters to (default: title in the file)')

    def handle(self, *args, **options):
        path = Path(options['path'])
        if not path.is_file():
            raise CommandError(f'{path} does not exist.')
        payload = json.loads(path.read_text(encoding='utf-8'))
        docs = payload.get('chapters') or []
        if not docs:
            raise CommandError(f'{path} holds no chapters.')

        if options['book']:
            book = find_book(options['book'])
        else:
            title = payload.get('book_title', '')
            book = Book.objects.filter(title=title).order_by('-id').first()
            if book is None:
                source = Path(settings.BOOKS_DIR) / f'{title}.txt'
                if not source.is_file():
                    raise CommandError(
                        f'No book titled {title!r} in the database and no {source}; pass --book or add the .txt.'
                    )
                book = Book.objects.create(
                    title=title, content=source.read_text(encoding='utf-8', errors='ignore'), source_type=LOCAL_SOURCE
                )
                self.stdout.write(f'Created book {book.id} "{title}" from {source}')

        count = MongoService.import_chapters(book_id=book.store_key, docs=docs)
        book.chapter_count = count
        book.save(update_fields=['chapter_count', 'updated_at'])
        progress = MongoService.chapter_progress(book_id=book.store_key)
        bible = payload.get('bible')
        if bible and bible.get('characters') is not None:
            MongoService.replace_bible(book_id=book.store_key, bible=bible, done_chapters=progress['done'])
            self.stdout.write(f"Restored bible: {len(bible['characters'])} characters, {len(bible.get('plot', []))} plot beats")
        else:
            stats = rebuild_bible(book)
            self.stdout.write(f"Rebuilt bible from summaries: {stats['characters']} characters (profiles need a prepare run)")
        self.stdout.write(
            f'Restored {count} chapters to book {book.id} "{book.title}": '
            f"{progress['done']} summarised, {progress['pending']} pending, {progress['failed']} failed"
        )
