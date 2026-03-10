from django.db import connection
from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Book, Character, InventoryItem, MarketItem, Merchant, MerchantInventory, StorySession, World
from .serializers import (
    AITradeSerializer,
    BookUploadSerializer,
    CharacterCreateSerializer,
    CharacterSerializer,
    InventoryItemSerializer,
    MarketBootstrapSerializer,
    MarketItemSerializer,
    MerchantInventorySerializer,
    MerchantSerializer,
    SessionInteractSerializer,
    SessionStartSerializer,
    StorySessionSerializer,
    TradeExecuteSerializer,
    TradeOrderSerializer,
    TradeQuoteSerializer,
    WorldGenerateSerializer,
    WorldSerializer,
)
from .services.mongo_service import MongoService
from .services.openai_service import OpenAIService
from .services.rule_layer import MarketRuleLayer
from .services.trade_service import TradeService


def _fallback_trade_intent(user_input: str, allowed_items: list[str]) -> dict:
    text = user_input.lower()
    action = 'sell' if any(k in text for k in ['sell', '出售', '卖']) else 'buy'
    strategy = 'fixed'
    if any(k in text for k in ['negot', 'bargain', '讲价', '讨价']):
        strategy = 'negotiation'
    elif any(k in text for k in ['barter', '交换', '以物易物']):
        strategy = 'barter'

    quantity = 1
    for token in text.replace(',', ' ').split():
        if token.isdigit():
            quantity = max(1, int(token))
            break

    chosen = allowed_items[0]
    for item in allowed_items:
        if item.lower() in text:
            chosen = item
            break

    return {'action': action, 'item_name': chosen, 'quantity': quantity, 'strategy': strategy}


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

        openai_result = OpenAIService().check()
        mongo_result = MongoService.ping()

        healthy = db_ok and openai_result['ok'] and mongo_result['ok']
        return Response(
            {
                'status': 'healthy' if healthy else 'degraded',
                'database': {'ok': db_ok, 'message': db_message},
                'openai': openai_result,
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
            generated = OpenAIService().generate_world(book_title=book.title, book_content=book.content)
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

        return Response({'world': WorldSerializer(world).data}, status=status.HTTP_201_CREATED)


class CharacterCreateView(APIView):
    def post(self, request):
        serializer = CharacterCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        character = serializer.save()
        return Response({'character': CharacterSerializer(character).data}, status=status.HTTP_201_CREATED)


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

        history = MongoService.get_conversation_history(session_id=session.id, limit=8)
        try:
            ai_output = OpenAIService().generate_story_turn(
                world_name=session.world.name,
                world_lore_summary=session.world.lore_summary,
                character_name=session.character.name,
                character_role=session.character.role,
                user_input=user_input,
                history=history,
            )
        except Exception as exc:
            StorySession.objects.filter(id=session.id).update(is_processing=False)
            return Response({'detail': f'Interaction failed: {str(exc)}'}, status=status.HTTP_502_BAD_GATEWAY)

        log_result = MongoService.insert_conversation_log(
            session_id=session.id,
            world_id=session.world_id,
            character_id=session.character_id,
            user_input=user_input,
            ai_output=ai_output,
        )
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
                'ai_output': ai_output,
                'history_saved': log_result.get('ok', False),
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
                'buyer_coins': buyer.coins,
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
            ai_data = OpenAIService().generate_market_candidates(
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

        try:
            intent = OpenAIService().parse_trade_intent(
                user_input=payload['user_input'],
                allowed_items=available_items,
            )
            intent_source = 'ai'
        except Exception:
            intent = _fallback_trade_intent(payload['user_input'], available_items)
            intent_source = 'rule_fallback'

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
