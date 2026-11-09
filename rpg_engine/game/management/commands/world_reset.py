"""Delete the generated world(s) of a book so the next prepare run builds a fresh one.

    python manage.py world_reset "十日终焉_前20章"

Sessions, characters, NPCs and market data of those worlds go with them. The chapter scan and
story bible in MongoDB are kept.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from game.models import World

from .chapters_export import find_book


class Command(BaseCommand):
    help = "Delete a book's generated worlds (sessions included); keeps the chapter scan."

    def add_arguments(self, parser):
        parser.add_argument('book', help='Book id or title')

    def handle(self, *args, **options):
        book = find_book(options['book'])
        worlds = World.objects.filter(book=book) | World.objects.filter(book__isnull=True, source_book_title=book.title)
        names = [w.name for w in worlds]
        worlds.delete()
        self.stdout.write(f'Deleted {len(names)} world(s) of "{book.title}": {", ".join(names) or "-"}')
