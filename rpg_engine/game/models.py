from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Book(TimeStampedModel):
    title = models.CharField(max_length=255)
    content = models.TextField()
    source_type = models.CharField(max_length=30, default='txt')

    def __str__(self) -> str:
        return self.title


class World(TimeStampedModel):
    book = models.ForeignKey(Book, on_delete=models.SET_NULL, null=True, blank=True, related_name='worlds')
    name = models.CharField(max_length=120)
    source_book_title = models.CharField(max_length=255, blank=True)
    lore_summary = models.TextField(blank=True)
    factions = models.JSONField(default=list, blank=True)
    locations = models.JSONField(default=list, blank=True)
    main_conflict = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class Character(TimeStampedModel):
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name='characters')
    name = models.CharField(max_length=120)
    role = models.CharField(max_length=80, blank=True)
    level = models.PositiveIntegerField(default=1)
    coins = models.BigIntegerField(default=100)

    def __str__(self) -> str:
        return f'{self.name} (Lv.{self.level})'


class StorySession(TimeStampedModel):
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name='sessions')
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name='sessions')
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=30, default='active')
    version = models.PositiveIntegerField(default=1)
    is_processing = models.BooleanField(default=False)
    last_turn_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.title


class InventoryItem(TimeStampedModel):
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name='inventory_items')
    item_name = models.CharField(max_length=120)
    quantity = models.PositiveIntegerField(default=0)
    avg_unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        unique_together = ('character', 'item_name')

    def __str__(self) -> str:
        return f'{self.item_name} x{self.quantity}'


class TradeOrder(TimeStampedModel):
    STRATEGY_FIXED = 'fixed'
    STRATEGY_NEGOTIATION = 'negotiation'
    STRATEGY_BARTER = 'barter'
    STRATEGY_CHOICES = [
        (STRATEGY_FIXED, 'Fixed Price'),
        (STRATEGY_NEGOTIATION, 'Negotiation'),
        (STRATEGY_BARTER, 'Barter'),
    ]

    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]
    SIDE_BUY = 'buy'
    SIDE_SELL = 'sell'
    SIDE_CHOICES = [
        (SIDE_BUY, 'Buy'),
        (SIDE_SELL, 'Sell'),
    ]

    session = models.ForeignKey(StorySession, on_delete=models.CASCADE, related_name='trade_orders')
    buyer = models.ForeignKey(Character, on_delete=models.CASCADE, related_name='buy_orders')
    side = models.CharField(max_length=10, choices=SIDE_CHOICES, default=SIDE_BUY)
    merchant_name = models.CharField(max_length=120, blank=True)
    item_name = models.CharField(max_length=120)
    quantity = models.PositiveIntegerField()
    strategy = models.CharField(max_length=30, choices=STRATEGY_CHOICES)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_COMPLETED)

    def __str__(self) -> str:
        return f'#{self.id} {self.item_name} x{self.quantity}'


class Merchant(TimeStampedModel):
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name='merchants')
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=120, blank=True)
    price_multiplier = models.DecimalField(max_digits=6, decimal_places=2, default=1.00)
    buyback_rate = models.DecimalField(max_digits=6, decimal_places=2, default=0.60)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('world', 'name')

    def __str__(self) -> str:
        return self.name


class MarketItem(TimeStampedModel):
    RARITY_COMMON = 'common'
    RARITY_RARE = 'rare'
    RARITY_EPIC = 'epic'
    RARITY_CHOICES = [
        (RARITY_COMMON, 'Common'),
        (RARITY_RARE, 'Rare'),
        (RARITY_EPIC, 'Epic'),
    ]

    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name='market_items')
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=60, blank=True)
    rarity = models.CharField(max_length=20, choices=RARITY_CHOICES, default=RARITY_COMMON)
    base_price = models.DecimalField(max_digits=12, decimal_places=2)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ('world', 'name')

    def __str__(self) -> str:
        return self.name


class MerchantInventory(TimeStampedModel):
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='inventory')
    market_item = models.ForeignKey(MarketItem, on_delete=models.CASCADE, related_name='merchant_inventory')
    stock = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('merchant', 'market_item')

    def __str__(self) -> str:
        return f'{self.merchant.name}: {self.market_item.name} x{self.stock}'
