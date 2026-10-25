"""Text REPL that drives the game loop directly through the service layer.

    python manage.py play --book path/to/book.txt --name Kai --role Ranger
    python manage.py play --session 3
    python manage.py play --book demo.txt --offline   # no OpenAI key needed
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from game.models import Book, Character, MarketItem, Merchant, MerchantInventory, StorySession, World
from game.services.factories import ComponentFactoryRegistry
from game.services.offline_narrator import OfflineNarrator
from game.services.openai_service import OpenAIService
from game.services.rule_layer import MarketRuleLayer
from game.services.story_service import StoryService
from game.services.trade_service import TradeService

HELP = """
Commands (anything else is sent to the narrator as your action):
  /status            HP, coins, location, status effects
  /inventory         what you carry
  /quests            active and finished quests
  /market            merchants here and their stock
  /buy <text>        e.g. /buy 2 traveler ration with negotiation
  /sell <text>       e.g. /sell 1 torch
  /help  /quit
"""


class Command(BaseCommand):
    help = 'Play the RPG in the terminal.'

    def add_arguments(self, parser):
        parser.add_argument('--book', help='Path to a .txt book to build a new world from.')
        parser.add_argument('--world', type=int, help='Existing world id (skips world generation).')
        parser.add_argument('--session', type=int, help='Resume an existing session id.')
        parser.add_argument('--name', default='Kai')
        parser.add_argument('--role', default='Ranger')
        parser.add_argument('--offline', action='store_true', help='Use the deterministic offline narrator.')

    # --- setup --------------------------------------------------------------

    def handle(self, *args, **opts):
        offline = opts['offline'] or not settings.OPENAI_API_KEY
        if offline and not opts['offline']:
            self.stdout.write(self.style.WARNING('OPENAI_API_KEY not set; using offline narrator.'))
        self.ai = OfflineNarrator() if offline else OpenAIService()
        self.story = StoryService(ai=self.ai)

        session = self._resolve_session(opts)
        self.session = session
        self.character = session.character
        self.world = session.world

        self.stdout.write(self.style.SUCCESS(f'\n=== {self.world.name} — {session.title} ==='))
        self.stdout.write(self.world.lore_summary[:300] + ('…' if len(self.world.lore_summary) > 300 else ''))
        self.stdout.write(HELP)
        self._status()
        self._loop()

    def _resolve_session(self, opts) -> StorySession:
        if opts['session']:
            try:
                return StorySession.objects.select_related('world', 'character').get(id=opts['session'])
            except StorySession.DoesNotExist as exc:
                raise CommandError(f'Session {opts["session"]} not found.') from exc

        if opts['world']:
            world = World.objects.filter(id=opts['world']).first()
            if world is None:
                raise CommandError(f'World {opts["world"]} not found.')
        elif opts['book']:
            world = self._build_world(Path(opts['book']))
        else:
            raise CommandError('Pass --book, --world or --session.')

        character = Character.objects.create(
            world=world, name=opts['name'], role=opts['role'], current_location=(world.locations or [''])[0]
        )
        return StorySession.objects.create(world=world, character=character, title=f"{character.name}'s Adventure")

    def _build_world(self, path: Path) -> World:
        if not path.is_file():
            raise CommandError(f'Book not found: {path}')
        content = path.read_text(encoding='utf-8', errors='ignore')
        book = Book.objects.create(title=path.stem, content=content)
        self.stdout.write(f'Generating world from "{book.title}"…')
        spec = self.ai.generate_world(book_title=book.title, book_content=book.content)
        world = World.objects.create(
            book=book,
            name=spec['world_name'],
            source_book_title=book.title,
            lore_summary=spec['lore_summary'],
            factions=spec['factions'],
            locations=spec['locations'],
            main_conflict=spec['main_conflict'],
        )
        loc_factory = ComponentFactoryRegistry.get('location', ai=self.ai)
        for name in spec['locations']:
            loc_factory.create(world=world, spec={'name': name})
        try:
            npcs = ComponentFactoryRegistry.get('npc', ai=self.ai).create_many(world=world, count=3)
            self.stdout.write(f'NPCs: {", ".join(n.name for n in npcs)}')
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f'NPC generation skipped: {exc}'))
        self._bootstrap_market(world, book)
        return world

    def _bootstrap_market(self, world: World, book: Book) -> None:
        try:
            data = self.ai.generate_market_candidates(
                world_name=world.name, world_lore_summary=world.lore_summary, book_title=book.title, book_content=book.content
            )
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f'Market generation skipped: {exc}'))
            return
        items = MarketRuleLayer.sanitize_items(data.get('items', []))
        merchants = MarketRuleLayer.sanitize_merchants(data.get('merchants', []))
        item_objs = []
        for item in items:
            obj, _ = MarketItem.objects.update_or_create(
                world=world,
                name=item['name'],
                defaults={'category': item['category'], 'rarity': item['rarity'], 'base_price': item['base_price']},
            )
            item_objs.append((obj, item['stock']))
        first_location = (world.locations or [''])[0]
        for m in merchants:
            merchant, _ = Merchant.objects.update_or_create(
                world=world,
                name=m['name'],
                defaults={
                    'location': m['location'] or first_location,
                    'price_multiplier': m['price_multiplier'],
                    'buyback_rate': m['buyback_rate'],
                },
            )
            for obj, stock in item_objs:
                MerchantInventory.objects.update_or_create(merchant=merchant, market_item=obj, defaults={'stock': stock})
        self.stdout.write(f'Market: {len(item_objs)} items, {len(merchants)} merchant(s)')

    # --- loop ---------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            if self.session.status != StorySession.STATUS_ACTIVE:
                self.stdout.write(self.style.NOTICE('This session has ended.'))
                return
            try:
                raw = input('\n> ').strip()
            except (EOFError, KeyboardInterrupt):
                self.stdout.write('\nFarewell.')
                return
            if not raw:
                continue
            if raw.startswith('/'):
                if self._command(raw):
                    return
                continue
            self._turn(raw)

    def _command(self, raw: str) -> bool:
        cmd, _, rest = raw[1:].partition(' ')
        cmd = cmd.lower()
        if cmd in {'quit', 'exit', 'q'}:
            self.stdout.write('Farewell.')
            return True
        if cmd == 'help':
            self.stdout.write(HELP)
        elif cmd == 'status':
            self._status()
        elif cmd in {'inventory', 'inv', 'i'}:
            self._inventory()
        elif cmd == 'quests':
            self._quests()
        elif cmd == 'market':
            self._market()
        elif cmd in {'buy', 'sell'}:
            self._trade(f'{cmd} {rest}')
        else:
            self.stdout.write(f'Unknown command /{cmd}. Try /help.')
        return False

    def _turn(self, user_input: str) -> None:
        try:
            result = self.story.play_turn(session=self.session, user_input=user_input)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'Narrator failed: {exc}'))
            return
        self.stdout.write('')
        self.stdout.write(result.narrative)
        for note in result.notes:
            self.stdout.write(self.style.NOTICE(f'  • {note}'))
        self.session.refresh_from_db()
        self.character.refresh_from_db()

    # --- info ---------------------------------------------------------------

    def _state(self) -> dict:
        self.character.refresh_from_db()
        return StoryService.state_snapshot(self.character, self.session)

    def _status(self) -> None:
        s = self._state()
        effects = ', '.join(s['status_effects']) or 'none'
        self.stdout.write(
            f"[{s['name']} the {s['role']} | Lv{s['level']} | HP {s['hp']}/{s['max_hp']} | "
            f"{s['coins']} coins | at {s['location'] or 'nowhere'} | effects: {effects}]"
        )
        if s['nearby_npcs']:
            self.stdout.write('  Nearby: ' + ', '.join(f"{n['name']} ({n['role']}, {n['disposition']})" for n in s['nearby_npcs']))
        if s['active_encounters']:
            self.stdout.write('  Encounters: ' + ', '.join(f"{e['title']} [{e['kind']} d{e['difficulty']}]" for e in s['active_encounters']))

    def _inventory(self) -> None:
        items = self._state()['inventory']
        self.stdout.write('Inventory: ' + (', '.join(f"{i['item_name']} x{i['quantity']}" for i in items) or 'empty'))

    def _quests(self) -> None:
        quests = self._state()['quests']
        if not quests:
            self.stdout.write('No quests yet.')
        for q in quests:
            self.stdout.write(f"  [{q['status']}] {q['title']} (+{q['reward_coins']} coins)")

    def _merchants_here(self):
        location = self._state()['location']
        qs = Merchant.objects.filter(world=self.world, is_active=True)
        here = qs.filter(location=location)
        return here if here.exists() else qs

    def _market(self) -> None:
        merchants = list(self._merchants_here())
        if not merchants:
            self.stdout.write('No merchants in this world.')
            return
        for m in merchants:
            self.stdout.write(f'{m.name} @ {m.location or "?"} (x{m.price_multiplier} buy, {m.buyback_rate} buyback)')
            for inv in m.inventory.select_related('market_item').order_by('market_item__name'):
                self.stdout.write(f'    {inv.market_item.name:<20} {inv.market_item.base_price:>7} coins  stock {inv.stock}')

    def _trade(self, text: str) -> None:
        merchant = self._merchants_here().first()
        if merchant is None:
            self.stdout.write('No merchant to trade with.')
            return
        allowed = list(MarketItem.objects.filter(world=self.world).values_list('name', flat=True).order_by('name'))
        if not allowed:
            self.stdout.write('The market is empty.')
            return
        intent, source = TradeService.parse_intent(user_input=text, allowed_items=allowed, ai=self.ai)
        try:
            order = TradeService.execute_market_trade(
                session_id=self.session.id,
                character_id=self.character.id,
                merchant_id=merchant.id,
                item_name=intent['item_name'],
                quantity=intent['quantity'],
                action=intent['action'],
                strategy_name=intent['strategy'],
            )
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'Trade failed: {exc}'))
            return
        verb = 'bought' if order.side == 'buy' else 'sold'
        self.stdout.write(
            self.style.SUCCESS(
                f'{merchant.name}: you {verb} {order.item_name} x{order.quantity} for {order.total_price} coins '
                f'({order.strategy}, parsed by {source}).'
            )
        )
        self._status()
