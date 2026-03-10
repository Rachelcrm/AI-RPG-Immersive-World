from decimal import Decimal

from rest_framework import serializers

from .models import Book, Character, InventoryItem, MarketItem, Merchant, MerchantInventory, StorySession, TradeOrder, World


class BookUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Book
        fields = ['id', 'title', 'content', 'source_type', 'created_at']
        read_only_fields = ['id', 'created_at']


class WorldGenerateSerializer(serializers.Serializer):
    book_id = serializers.IntegerField(min_value=1)


class WorldSerializer(serializers.ModelSerializer):
    class Meta:
        model = World
        fields = [
            'id',
            'book',
            'name',
            'source_book_title',
            'lore_summary',
            'factions',
            'locations',
            'main_conflict',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class CharacterCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Character
        fields = ['id', 'world', 'name', 'role', 'level', 'coins', 'created_at']
        read_only_fields = ['id', 'level', 'coins', 'created_at']


class CharacterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Character
        fields = ['id', 'world', 'name', 'role', 'level', 'coins', 'created_at']


class SessionStartSerializer(serializers.Serializer):
    world_id = serializers.IntegerField(min_value=1)
    character_id = serializers.IntegerField(min_value=1)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)


class StorySessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorySession
        fields = ['id', 'world', 'character', 'title', 'status', 'version', 'is_processing', 'last_turn_at', 'created_at']


class SessionInteractSerializer(serializers.Serializer):
    user_input = serializers.CharField(min_length=1, max_length=2000)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class TradeQuoteSerializer(serializers.Serializer):
    character_id = serializers.IntegerField(min_value=1)
    item_name = serializers.CharField(min_length=1, max_length=120)
    quantity = serializers.IntegerField(min_value=1, max_value=9999)
    base_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    strategy = serializers.ChoiceField(choices=['fixed', 'negotiation', 'barter'])


class TradeExecuteSerializer(TradeQuoteSerializer):
    session_id = serializers.IntegerField(min_value=1)


class InventoryItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryItem
        fields = ['id', 'item_name', 'quantity', 'avg_unit_price']


class TradeOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeOrder
        fields = [
            'id',
            'session',
            'buyer',
            'side',
            'merchant_name',
            'item_name',
            'quantity',
            'strategy',
            'unit_price',
            'subtotal',
            'tax_amount',
            'total_price',
            'status',
            'created_at',
        ]


class MarketBootstrapSerializer(serializers.Serializer):
    world_id = serializers.IntegerField(min_value=1)
    book_id = serializers.IntegerField(min_value=1, required=False)
    reset_existing = serializers.BooleanField(default=False)


class MarketItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketItem
        fields = ['id', 'world', 'name', 'category', 'rarity', 'base_price', 'metadata']


class MerchantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = ['id', 'world', 'name', 'location', 'price_multiplier', 'buyback_rate', 'is_active']


class MerchantInventorySerializer(serializers.ModelSerializer):
    market_item = MarketItemSerializer(read_only=True)

    class Meta:
        model = MerchantInventory
        fields = ['id', 'market_item', 'stock']


class AITradeSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    merchant_id = serializers.IntegerField(min_value=1)
    user_input = serializers.CharField(min_length=2, max_length=2000)
