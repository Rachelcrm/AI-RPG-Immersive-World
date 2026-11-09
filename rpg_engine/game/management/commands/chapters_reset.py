"""Mark a book's chapters pending again so the next prepare run re-scans them (costs model calls).

    python manage.py chapters_reset "十日终焉_前20章"

Use after changing what the scan extracts. The chapter text is kept; summaries, the story bible
and its character profiles are dropped and rebuilt on the next run.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from game.services.mongo_service import MongoService

from .chapters_export import find_book


class Command(BaseCommand):
    help = "Reset a book's chapters to pending and drop its story bible."

    def add_arguments(self, parser):
        parser.add_argument('book', help='Book id or title')

    def handle(self, *args, **options):
        book = find_book(options['book'])
        count = MongoService.reset_chapters(book_id=book.store_key)
        MongoService.delete_bible(book_id=book.store_key)
        self.stdout.write(f'Reset {count} chapters of book {book.id} "{book.title}"; run prepare to scan them again.')
