from django.contrib import admin

from .models import (
    Book,
    Character,
    InventoryItem,
    MarketItem,
    Merchant,
    MerchantInventory,
    StorySession,
    TradeOrder,
    World,
)

admin.site.register(Book)
admin.site.register(World)
admin.site.register(Character)
admin.site.register(StorySession)
admin.site.register(InventoryItem)
admin.site.register(TradeOrder)
admin.site.register(Merchant)
admin.site.register(MarketItem)
admin.site.register(MerchantInventory)
