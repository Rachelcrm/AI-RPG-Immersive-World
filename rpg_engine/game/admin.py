from django.contrib import admin

from .models import (
    Book,
    Character,
    Encounter,
    InventoryItem,
    Location,
    NPC,
    MarketItem,
    Merchant,
    MerchantInventory,
    Quest,
    StorySession,
    TradeOrder,
    World,
)

admin.site.register(Book)
admin.site.register(World)
admin.site.register(Character)
admin.site.register(StorySession)
admin.site.register(Quest)
admin.site.register(Location)
admin.site.register(NPC)
admin.site.register(Encounter)
admin.site.register(InventoryItem)
admin.site.register(TradeOrder)
admin.site.register(Merchant)
admin.site.register(MarketItem)
admin.site.register(MerchantInventory)
