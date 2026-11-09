"""Print a book's story bible: characters (with profiles), plot beats and facts.

    python manage.py bible_show "十日终焉_前20章"
    python manage.py bible_show "十日终焉_前20章" --character 齐夏
    python manage.py bible_show "十日终焉_前20章" --plot --facts
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from game.services.mongo_service import MongoService

from .chapters_export import find_book


class Command(BaseCommand):
    help = "Show a book's story bible."

    def add_arguments(self, parser):
        parser.add_argument('book', help='Book id or title')
        parser.add_argument('--character', help='Full record of one character (name or alias)')
        parser.add_argument('--plot', action='store_true', help='List every plot beat')
        parser.add_argument('--facts', action='store_true', help='List every fact')

    def handle(self, *args, **options):
        book = find_book(options['book'])
        characters = MongoService.get_characters(book_id=book.store_key)
        if not characters:
            raise CommandError(f'Book {book.id} "{book.title}" has no story bible yet (run prepare first).')
        if options['character']:
            wanted = options['character'].strip().lower()
            hit = next(
                (c for c in characters if c['name'].lower() == wanted or wanted in [a.lower() for a in c.get('aliases', [])]),
                None,
            )
            if hit is None:
                raise CommandError(f'No character named {options["character"]!r}.')
            self.stdout.write(json.dumps(hit, ensure_ascii=False, indent=1))
            return
        plot = MongoService.get_plot(book_id=book.store_key)
        facts = MongoService.get_facts(book_id=book.store_key)
        self.stdout.write(f'"{book.title}": {len(characters)} characters, {len(plot)} plot beats, {len(facts)} facts\n')
        for c in characters:
            profile = c.get('profile') or {}
            tags = ', '.join(profile.get('style_tags', []))
            marker = '*' if c['importance'] == 'major' else ' '
            state = 'profile' if profile.get('personality') else ('profile FAILED' if profile.get('error') else 'no profile')
            self.stdout.write(
                f"{marker} {c['name']:<12} ch{c['first_chapter']}-{c['last_chapter']} ({len(c['chapters'])} units) "
                f"{c.get('identity', '')[:40]:<40} quotes={len(c['quotes'])} [{state}{': ' + tags if tags else ''}]"
            )
        if options['plot']:
            self.stdout.write('\nPlot:')
            for b in plot:
                self.stdout.write(f"  {b['sequence']:>3}. ch{b['chapter']} [{b['type']}] {b['description']}")
        if options['facts']:
            self.stdout.write('\nFacts:')
            for f in facts:
                self.stdout.write(f"  ch{f['chapter']} ({f['category']}) {f['content']}")
