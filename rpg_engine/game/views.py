from django.db import connection
from django.db.models import F
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Book, Character, InventoryItem, MarketItem, Merchant, MerchantInventory, StorySession, World
from .serializers import (
    AITradeSerializer,
    BookProcessSerializer,
    BookUploadSerializer,
    CharacterCreateSerializer,
    CharacterSerializer,
    ComponentGenerateSerializer,
    EncounterSerializer,
    InventoryItemSerializer,
    LocationSerializer,
    MarketBootstrapSerializer,
    MarketItemSerializer,
    MerchantInventorySerializer,
    MerchantSerializer,
    NPCSerializer,
    PlayPrepareSerializer,
    PlayStartSerializer,
    SessionInteractSerializer,
    SessionStartSerializer,
    StorySessionSerializer,
    TradeExecuteSerializer,
    TradeOrderSerializer,
    TradeQuoteSerializer,
    WorldGenerateSerializer,
    WorldSerializer,
)
from .services.factories import ComponentFactoryRegistry
from .services.mongo_service import MongoService
from .services.llm_service import get_llm_service
from .services.rule_layer import MarketRuleLayer
from .services.story_service import StoryService
from .services.trade_service import TradeService
from .services.world_builder import (
    DEFAULT_BATCH,
    book_for_local_file,
    build_world_from_book,
    build_world_from_file,
    chapter_list,
    ensure_bible,
    ingest_book,
    list_local_books,
    opening_objective,
    process_chapters,
    resolve_local_book,
    starting_location,
)


class HealthView(APIView):
    def get(self, request):
        db_ok = True
        db_message = 'ok'
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
        except Exception as exc:
            db_ok = False
            db_message = str(exc)

        llm_result = get_llm_service().check()
        mongo_result = MongoService.ping()

        healthy = db_ok and llm_result['ok'] and mongo_result['ok']
        return Response(
            {
                'status': 'healthy' if healthy else 'degraded',
                'database': {'ok': db_ok, 'message': db_message},
                'llm': llm_result,
                'mongodb': mongo_result,
            }
        )


class BookUploadView(APIView):
    def post(self, request):
        serializer = BookUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        book = serializer.save()
        return Response({'book': BookUploadSerializer(book).data}, status=status.HTTP_201_CREATED)


class WorldGenerateView(APIView):
    def post(self, request):
        serializer = WorldGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        book_id = serializer.validated_data['book_id']
        try:
            book = Book.objects.get(id=book_id)
        except Book.DoesNotExist:
            return Response({'detail': f'Book {book_id} not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            summaries = MongoService.get_chapter_summaries(book_id=book.store_key)
            generated = get_llm_service().generate_world(
                book_title=book.title, book_content=book.content, chapter_summaries=summaries
            )
        except Exception as exc:
            return Response({'detail': f'World generation failed: {str(exc)}'}, status=status.HTTP_502_BAD_GATEWAY)

        world = World.objects.create(
            book=book,
            name=generated['world_name'],
            source_book_title=book.title,
            lore_summary=generated['lore_summary'],
            factions=generated['factions'],
            locations=generated['locations'],
            main_conflict=generated['main_conflict'],
        )

        # Locations come straight from the world spec (no extra AI call);
        # NPCs need a second generation and are best-effort.
        location_factory = ComponentFactoryRegistry.get('location')
        locations = []
        for name in generated['locations']:
            try:
                locations.append(location_factory.create(world=world, spec={'name': name}))
            except ValueError:
                continue

        npcs, npc_error = [], None
        try:
            npcs = ComponentFactoryRegistry.get('npc').create_many(world=world, count=3)
        except Exception as exc:
            npc_error = str(exc)

        return Response(
            {
                'world': WorldSerializer(world).data,
                'locations': LocationSerializer(locations, many=True).data,
                'npcs': NPCSerializer(npcs, many=True).data,
                'npc_error': npc_error,
            },
            status=status.HTTP_201_CREATED,
        )


class WorldComponentGenerateView(APIView):
    """Create game components on demand: AI-generated, or from a caller-supplied spec."""

    _serializers = {
        'location': LocationSerializer,
        'npc': NPCSerializer,
        'item': MarketItemSerializer,
        'encounter': EncounterSerializer,
    }

    def post(self, request, world_id: int):
        serializer = ComponentGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            world = World.objects.get(id=world_id)
        except World.DoesNotExist:
            return Response({'detail': f'World {world_id} not found.'}, status=status.HTTP_404_NOT_FOUND)

        session = None
        if payload.get('session_id'):
            session = StorySession.objects.filter(id=payload['session_id'], world=world).first()
            if session is None:
                return Response({'detail': 'Session not found in this world.'}, status=status.HTTP_404_NOT_FOUND)
        if payload['kind'] == 'encounter' and session is None:
            return Response({'detail': 'session_id is required for encounters.'}, status=status.HTTP_400_BAD_REQUEST)

        factory = ComponentFactoryRegistry.get(payload['kind'])
        try:
            if payload.get('spec'):
                components = [factory.create(world=world, spec=payload['spec'], session=session)]
            else:
                components = factory.create_many(
                    world=world, count=payload['count'], session=session, hint=payload['hint']
                )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'detail': f'Component generation failed: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                'kind': payload['kind'],
                'components': self._serializers[payload['kind']](components, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CharacterCreateView(APIView):
    def post(self, request):
        serializer = CharacterCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        character = serializer.save()
        return Response({'character': CharacterSerializer(character).data}, status=status.HTTP_201_CREATED)


@method_decorator(ensure_csrf_cookie, name='dispatch')
class PlayPageView(TemplateView):
    template_name = 'game/play.html'


class LocalBookListView(APIView):
    def get(self, request):
        return Response({'books': list_local_books()}, status=status.HTTP_200_OK)


def _progress_payload(book: Book, progress: dict, world: World | None) -> dict:
    return {
        'book_id': book.id,
        'book_title': book.title,
        'chapter_count': book.chapter_count,
        **progress,
        'profiles_pending': progress.get('profiles_pending', 0),
        'ready': world is not None,
        'world_id': world.id if world else None,
    }


def _advance_book(book: Book, batch: int) -> tuple[dict, World | None, str | None]:
    """One step of the pipeline: split, or summarise a batch, or build the world. Returns (progress, world, error).

    Each call does a bounded amount of work so it fits in one short HTTP request; the client
    keeps calling until `ready`. Steps already done are skipped, so retries are safe.
    """
    world = World.objects.filter(book=book).order_by('-id').first()
    progress = ingest_book(book)
    if progress['pending']:
        # Also runs for an existing world whose summaries were lost (in-memory store, restart):
        # the chapter picker and the narrator need them back.
        progress = process_chapters(book, get_llm_service(), batch=batch)
        if progress['pending']:
            return progress, None, None
    # Hard facts (characters, plot, rules) are merged from the summaries without model calls; the
    # overall profile of each major character is one model call, a few per request.
    remaining = ensure_bible(book, get_llm_service(), batch=batch)
    if remaining:
        return {**progress, 'profiles_pending': remaining}, None, None
    if world is not None:
        return progress, world, None
    try:
        world = build_world_from_book(book, get_llm_service())
    except Exception as exc:
        return progress, None, f'World generation failed: {exc}'
    return progress, world, None


class BookProcessView(APIView):
    """Advance an uploaded book through the chapter pipeline, one batch per call."""

    def post(self, request, book_id: int):
        serializer = BookProcessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            book = Book.objects.get(id=book_id)
        except Book.DoesNotExist:
            return Response({'detail': f'Book {book_id} not found.'}, status=status.HTTP_404_NOT_FOUND)
        progress, world, error = _advance_book(book, serializer.validated_data.get('batch') or DEFAULT_BATCH)
        if error:
            return Response({'detail': error, **_progress_payload(book, progress, None)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(_progress_payload(book, progress, world), status=status.HTTP_200_OK)

    def get(self, request, book_id: int):
        try:
            book = Book.objects.get(id=book_id)
        except Book.DoesNotExist:
            return Response({'detail': f'Book {book_id} not found.'}, status=status.HTTP_404_NOT_FOUND)
        world = World.objects.filter(book=book).order_by('-id').first()
        return Response(_progress_payload(book, MongoService.chapter_progress(book_id=book.store_key), world))


class PlayPrepareView(APIView):
    """Same as BookProcessView, for a book in the local samples folder. The web UI polls this before /play/start/."""

    def post(self, request):
        serializer = PlayPrepareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        path = resolve_local_book(data['book'])
        if path is None:
            return Response({'detail': f"Book {data['book']!r} not found."}, status=status.HTTP_404_NOT_FOUND)
        book = book_for_local_file(path)
        # Worlds built before books were tracked per file are keyed by title only.
        legacy_world = World.objects.filter(book__isnull=True, source_book_title=path.stem).order_by('-id').first()
        if legacy_world is not None and not World.objects.filter(book=book).exists():
            legacy_world.book = book
            legacy_world.save(update_fields=['book', 'updated_at'])
        progress, world, error = _advance_book(book, data.get('batch') or DEFAULT_BATCH)
        if error:
            return Response({'detail': error, **_progress_payload(book, progress, None)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(_progress_payload(book, progress, world), status=status.HTTP_200_OK)


class PlayChaptersView(APIView):
    """Chapter titles and digests of a prepared local book, for picking where the adventure starts."""

    def get(self, request):
        file_name = request.query_params.get('book', '')
        path = resolve_local_book(file_name)
        if path is None:
            return Response({'detail': f'Book {file_name!r} not found.'}, status=status.HTTP_404_NOT_FOUND)
        book = book_for_local_file(path)
        return Response(
            {
                'book_id': book.id,
                'book_title': book.title,
                'chapter_count': book.chapter_count,
                **MongoService.chapter_progress(book_id=book.store_key),
                'chapters': chapter_list(book),
            }
        )


class PlayStartView(APIView):
    """One call for the web UI: pick a local book, get a session back.

    The world is generated once per book file and reused afterwards, so
    starting a new game is instant after the first run.
    """

    def post(self, request):
        serializer = PlayStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        path = resolve_local_book(data['book'])
        if path is None:
            return Response({'detail': f"Book {data['book']!r} not found."}, status=status.HTTP_404_NOT_FOUND)

        world = World.objects.filter(source_book_title=path.stem).order_by('-id').first()
        if world is None:
            try:
                world = build_world_from_file(path, get_llm_service())
            except Exception as exc:
                return Response({'detail': f'World generation failed: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

        chapter_count = world.book.chapter_count if world.book_id else 0
        start_chapter = min(data.get('start_chapter') or 1, chapter_count) if chapter_count else 1
        character = Character.objects.create(
            world=world,
            name=data['name'],
            role=data['role'] or 'Adventurer',
            current_location=starting_location(world, start_chapter),
        )
        opening = next((c for c in chapter_list(world.book) if c['index'] == start_chapter), None) if world.book_id else None
        session = StorySession.objects.create(
            world=world,
            character=character,
            title=f"{character.name}'s Adventure",
            current_chapter=start_chapter,
            objective=opening_objective(opening),
        )
        return Response(
            {
                'session': StorySessionSerializer(session).data,
                'world': WorldSerializer(world).data,
                'book_title': path.stem,
                'state': StoryService.state_snapshot(character, session),
                'chapter': opening,
            },
            status=status.HTTP_201_CREATED,
        )


class SessionStartView(APIView):
    def post(self, request):
        serializer = SessionStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        world_id = serializer.validated_data['world_id']
        character_id = serializer.validated_data['character_id']
        title = serializer.validated_data.get('title') or 'Adventure Session'

        try:
            world = World.objects.get(id=world_id)
        except World.DoesNotExist:
            return Response({'detail': f'World {world_id} not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            character = Character.objects.get(id=character_id)
        except Character.DoesNotExist:
            return Response({'detail': f'Character {character_id} not found.'}, status=status.HTTP_404_NOT_FOUND)

        if character.world_id != world.id:
            return Response(
                {'detail': 'Character does not belong to this world.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        session = StorySession.objects.create(world=world, character=character, title=title, status='active')
        return Response({'session': StorySessionSerializer(session).data}, status=status.HTTP_201_CREATED)


class SessionStateView(APIView):
    def get(self, request, session_id: int):
        try:
            session = StorySession.objects.select_related('world', 'character').get(id=session_id)
        except StorySession.DoesNotExist:
            return Response({'detail': f'Session {session_id} not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                'session': StorySessionSerializer(session).data,
                'state': StoryService.state_snapshot(session.character, session),
                'history': MongoService.get_conversation_history(session_id=session.id, limit=20),
            },
            status=status.HTTP_200_OK,
        )


class SessionInteractView(APIView):
    def post(self, request, session_id: int):
        serializer = SessionInteractSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_input = serializer.validated_data['user_input']
        expected_version = serializer.validated_data.get('expected_version')

        try:
            session = StorySession.objects.select_related('world', 'character').get(id=session_id)
        except StorySession.DoesNotExist:
            return Response({'detail': f'Session {session_id} not found.'}, status=status.HTTP_404_NOT_FOUND)

        if session.status != 'active':
            return Response({'detail': 'Session is not active.'}, status=status.HTTP_400_BAD_REQUEST)
        if expected_version is not None and session.version != expected_version:
            return Response(
                {
                    'detail': 'Version conflict.',
                    'session_id': session.id,
                    'current_version': session.version,
                    'expected_version': expected_version,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Atomic claim: only one concurrent request can enter processing phase.
        claim_filter = {'id': session.id, 'status': 'active', 'is_processing': False}
        if expected_version is not None:
            claim_filter['version'] = expected_version
        claimed = StorySession.objects.filter(**claim_filter).update(is_processing=True)
        if claimed == 0:
            latest = StorySession.objects.get(id=session.id)
            return Response(
                {
                    'detail': 'Session is being processed or version is stale.',
                    'session_id': latest.id,
                    'current_version': latest.version,
                    'is_processing': latest.is_processing,
                },
                status=status.HTTP_409_CONFLICT,
            )

        session.refresh_from_db()

        try:
            result = StoryService().play_turn(session=session, user_input=user_input)
        except Exception as exc:
            StorySession.objects.filter(id=session.id).update(is_processing=False)
            return Response({'detail': f'Interaction failed: {str(exc)}'}, status=status.HTTP_502_BAD_GATEWAY)

        StorySession.objects.filter(id=session.id).update(
            is_processing=False,
            version=F('version') + 1,
            last_turn_at=timezone.now(),
        )
        session.refresh_from_db()

        return Response(
            {
                'session_id': session.id,
                'session_version': session.version,
                'user_input': user_input,
                'ai_output': result.narrative,
                'events': [e.to_dict() for e in result.events],
                'notes': result.notes,
                'state': result.state,
                'session_status': result.session_status,
                'history_saved': result.history_saved,
                'objective': result.objective,
            },
            status=status.HTTP_200_OK,
        )


class TradeQuoteView(APIView):
    def post(self, request):
        serializer = TradeQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            character = Character.objects.get(id=payload['character_id'])
        except Character.DoesNotExist:
            return Response({'detail': 'Character not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            quote = TradeService.quote(
                strategy_name=payload['strategy'],
                character=character,
                base_price=payload['base_price'],
                quantity=payload['quantity'],
            )
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                'item_name': payload['item_name'],
                'quantity': payload['quantity'],
                'strategy': quote.strategy,
                'unit_price': str(quote.unit_price),
                'subtotal': str(quote.subtotal),
                'tax_amount': str(quote.tax_amount),
                'total_price': str(quote.total_price),
            },
            status=status.HTTP_200_OK,
        )


class TradeExecuteView(APIView):
    def post(self, request):
        serializer = TradeExecuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            order = TradeService.execute(
                session_id=payload['session_id'],
                character_id=payload['character_id'],
                item_name=payload['item_name'],
                quantity=payload['quantity'],
                base_price=payload['base_price'],
                strategy_name=payload['strategy'],
            )
        except StorySession.DoesNotExist:
            return Response({'detail': 'Session not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Character.DoesNotExist:
            return Response({'detail': 'Character not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        buyer = order.buyer
        inventory_items = InventoryItem.objects.filter(character=buyer).order_by('item_name')
        return Response(
            {
                'order': TradeOrderSerializer(order).data,
                'buyer_coins': str(buyer.coins),
                'inventory': InventoryItemSerializer(inventory_items, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )


class MarketBootstrapView(APIView):
    def post(self, request):
        serializer = MarketBootstrapSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        world_id = payload['world_id']
        try:
            world = World.objects.get(id=world_id)
        except World.DoesNotExist:
            return Response({'detail': 'World not found.'}, status=status.HTTP_404_NOT_FOUND)

        if payload.get('book_id'):
            try:
                book = Book.objects.get(id=payload['book_id'])
            except Book.DoesNotExist:
                return Response({'detail': 'Book not found.'}, status=status.HTTP_404_NOT_FOUND)
        elif world.book_id:
            book = world.book
        else:
            return Response({'detail': 'No book found for this world. Provide book_id.'}, status=status.HTTP_400_BAD_REQUEST)

        ai_error = None
        try:
            ai_data = get_llm_service().generate_market_candidates(
                world_name=world.name,
                world_lore_summary=world.lore_summary,
                book_title=book.title,
                book_content=book.content,
            )
        except Exception as exc:
            ai_error = str(exc)
            ai_data = {'items': [], 'merchants': []}

        items = MarketRuleLayer.sanitize_items(ai_data.get('items', []))
        merchants = MarketRuleLayer.sanitize_merchants(ai_data.get('merchants', []))

        if payload.get('reset_existing', False):
            MerchantInventory.objects.filter(merchant__world=world).delete()
            Merchant.objects.filter(world=world).delete()
            MarketItem.objects.filter(world=world).delete()

        item_objs = []
        for item in items:
            obj, _ = MarketItem.objects.update_or_create(
                world=world,
                name=item['name'],
                defaults={
                    'category': item['category'],
                    'rarity': item['rarity'],
                    'base_price': item['base_price'],
                    'metadata': {},
                },
            )
            item_objs.append((obj, item['stock']))

        merchant_objs = []
        for merchant in merchants:
            obj, _ = Merchant.objects.update_or_create(
                world=world,
                name=merchant['name'],
                defaults={
                    'location': merchant['location'],
                    'price_multiplier': merchant['price_multiplier'],
                    'buyback_rate': merchant['buyback_rate'],
                    'is_active': True,
                },
            )
            merchant_objs.append(obj)

        for merchant in merchant_objs:
            for item_obj, stock in item_objs:
                MerchantInventory.objects.update_or_create(
                    merchant=merchant,
                    market_item=item_obj,
                    defaults={'stock': stock},
                )

        return Response(
            {
                'world_id': world.id,
                'ai_fallback_used': ai_error is not None,
                'ai_error': ai_error,
                'items_count': len(item_objs),
                'merchants_count': len(merchant_objs),
                'items': MarketItemSerializer([i[0] for i in item_objs], many=True).data,
                'merchants': MerchantSerializer(merchant_objs, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )


class AITradeView(APIView):
    def post(self, request):
        serializer = AITradeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            session = StorySession.objects.select_related('world', 'character').get(id=payload['session_id'])
        except StorySession.DoesNotExist:
            return Response({'detail': 'Session not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            merchant = Merchant.objects.get(id=payload['merchant_id'], world_id=session.world_id, is_active=True)
        except Merchant.DoesNotExist:
            return Response({'detail': 'Merchant not found.'}, status=status.HTTP_404_NOT_FOUND)

        available_items = list(
            MarketItem.objects.filter(world_id=session.world_id).values_list('name', flat=True).order_by('name')
        )
        if not available_items:
            return Response({'detail': 'No market items found. Run /api/market/bootstrap/ first.'}, status=status.HTTP_400_BAD_REQUEST)

        intent, intent_source = TradeService.parse_intent(
            user_input=payload['user_input'], allowed_items=available_items
        )

        try:
            order = TradeService.execute_market_trade(
                session_id=session.id,
                character_id=session.character_id,
                merchant_id=merchant.id,
                item_name=intent['item_name'],
                quantity=intent['quantity'],
                action=intent['action'],
                strategy_name=intent['strategy'],
            )
        except Exception as exc:
            return Response({'detail': f'AI trade failed: {str(exc)}'}, status=status.HTTP_400_BAD_REQUEST)

        inventory_items = InventoryItem.objects.filter(character_id=session.character_id).order_by('item_name')
        merchant_inventory = MerchantInventory.objects.filter(merchant=merchant).select_related('market_item').order_by(
            'market_item__name'
        )
        return Response(
            {
                'intent': intent,
                'intent_source': intent_source,
                'order': TradeOrderSerializer(order).data,
                'character': CharacterSerializer(session.character).data,
                'inventory': InventoryItemSerializer(inventory_items, many=True).data,
                'merchant_inventory': MerchantInventorySerializer(merchant_inventory, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )
