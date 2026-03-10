from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from threading import Lock

from django.conf import settings
from django.db import transaction

from game.models import Character, InventoryItem, MarketItem, Merchant, MerchantInventory, StorySession, TradeOrder

MONEY_Q = Decimal('0.01')


def money(value: Decimal | float | int) -> Decimal:
    return Decimal(value).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


class CurrencyManager:
    _instance: CurrencyManager | None = None
    _lock = Lock()

    def __new__(cls) -> CurrencyManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.base_currency = 'GOLD'
                    cls._instance.tax_rate = Decimal(str(getattr(settings, 'TRADE_TAX_RATE', '0.05')))
        return cls._instance

    def compute_tax(self, subtotal: Decimal) -> Decimal:
        return money(subtotal * self.tax_rate)


@dataclass
class QuoteResult:
    strategy: str
    unit_price: Decimal
    subtotal: Decimal
    tax_amount: Decimal
    total_price: Decimal


class TradeStrategy:
    name = 'base'

    def unit_price(self, *, base_price: Decimal, character: Character, quantity: int) -> Decimal:
        return base_price


class FixedPriceStrategy(TradeStrategy):
    name = 'fixed'

    def unit_price(self, *, base_price: Decimal, character: Character, quantity: int) -> Decimal:
        return base_price


class NegotiationStrategy(TradeStrategy):
    name = 'negotiation'

    def unit_price(self, *, base_price: Decimal, character: Character, quantity: int) -> Decimal:
        role = (character.role or '').lower()
        discount = Decimal('0.10') if role in {'merchant', 'diplomat', 'bard'} else Decimal('0.04')
        if quantity >= 10:
            discount += Decimal('0.03')
        return money(base_price * (Decimal('1.00') - discount))


class BarterStrategy(TradeStrategy):
    name = 'barter'

    def unit_price(self, *, base_price: Decimal, character: Character, quantity: int) -> Decimal:
        # MVP barter: assume player can provide equivalent resources for 15% discount.
        return money(base_price * Decimal('0.85'))


class TradeStrategyFactory:
    _strategies = {
        'fixed': FixedPriceStrategy,
        'negotiation': NegotiationStrategy,
        'barter': BarterStrategy,
    }

    @classmethod
    def create(cls, name: str) -> TradeStrategy:
        strategy_cls = cls._strategies.get(name)
        if strategy_cls is None:
            raise ValueError(f'Unsupported strategy: {name}')
        return strategy_cls()


class TradeService:
    @staticmethod
    def resolve_market_item_name(*, world_id: int, requested_name: str) -> str:
        normalized = requested_name.strip().lower()
        if not normalized:
            raise ValueError('Item name is empty.')
        exact = MarketItem.objects.filter(world_id=world_id, name__iexact=normalized).first()
        if exact:
            return exact.name
        partial = MarketItem.objects.filter(world_id=world_id, name__icontains=normalized).first()
        if partial:
            return partial.name
        raise ValueError(f'Item "{requested_name}" not found in market.')

    @staticmethod
    def quote(*, strategy_name: str, character: Character, base_price: Decimal, quantity: int) -> QuoteResult:
        strategy = TradeStrategyFactory.create(strategy_name)
        unit_price = money(strategy.unit_price(base_price=base_price, character=character, quantity=quantity))
        subtotal = money(unit_price * quantity)
        tax_amount = CurrencyManager().compute_tax(subtotal)
        total_price = money(subtotal + tax_amount)
        return QuoteResult(
            strategy=strategy.name,
            unit_price=unit_price,
            subtotal=subtotal,
            tax_amount=tax_amount,
            total_price=total_price,
        )

    @staticmethod
    @transaction.atomic
    def execute(
        *,
        session_id: int,
        character_id: int,
        item_name: str,
        quantity: int,
        base_price: Decimal,
        strategy_name: str,
    ) -> TradeOrder:
        session = StorySession.objects.select_for_update().select_related('character').get(id=session_id)
        if session.status != 'active':
            raise ValueError('Session is not active.')
        if session.character_id != character_id:
            raise ValueError('Character does not belong to this session.')

        character = Character.objects.select_for_update().get(id=character_id)
        quote = TradeService.quote(
            strategy_name=strategy_name,
            character=character,
            base_price=base_price,
            quantity=quantity,
        )

        if Decimal(character.coins) < quote.total_price:
            raise ValueError('Insufficient coins.')

        character.coins = int(Decimal(character.coins) - quote.total_price)
        character.save(update_fields=['coins', 'updated_at'])

        inventory, _ = InventoryItem.objects.select_for_update().get_or_create(
            character=character,
            item_name=item_name,
            defaults={'quantity': 0, 'avg_unit_price': money(0)},
        )
        old_qty = inventory.quantity
        new_qty = old_qty + quantity
        old_total = money(inventory.avg_unit_price * old_qty)
        new_total = old_total + quote.subtotal
        inventory.quantity = new_qty
        inventory.avg_unit_price = money(new_total / new_qty)
        inventory.save(update_fields=['quantity', 'avg_unit_price', 'updated_at'])

        return TradeOrder.objects.create(
            session=session,
            buyer=character,
            side=TradeOrder.SIDE_BUY,
            merchant_name='System Market',
            item_name=item_name,
            quantity=quantity,
            strategy=quote.strategy,
            unit_price=quote.unit_price,
            subtotal=quote.subtotal,
            tax_amount=quote.tax_amount,
            total_price=quote.total_price,
            status=TradeOrder.STATUS_COMPLETED,
        )

    @staticmethod
    @transaction.atomic
    def execute_market_trade(
        *,
        session_id: int,
        character_id: int,
        merchant_id: int,
        item_name: str,
        quantity: int,
        action: str,
        strategy_name: str,
    ) -> TradeOrder:
        session = StorySession.objects.select_for_update().select_related('world').get(id=session_id)
        if session.status != 'active':
            raise ValueError('Session is not active.')
        if session.character_id != character_id:
            raise ValueError('Character does not belong to this session.')

        character = Character.objects.select_for_update().get(id=character_id)
        merchant = Merchant.objects.select_for_update().get(id=merchant_id, world_id=session.world_id, is_active=True)
        canonical_item_name = TradeService.resolve_market_item_name(world_id=session.world_id, requested_name=item_name)
        market_item = MarketItem.objects.get(world_id=session.world_id, name=canonical_item_name)
        merchant_inventory = MerchantInventory.objects.select_for_update().get(
            merchant=merchant,
            market_item=market_item,
        )

        action = action.lower().strip()
        if action not in {'buy', 'sell'}:
            raise ValueError('action must be buy or sell.')

        if action == 'buy':
            if merchant_inventory.stock < quantity:
                raise ValueError('Merchant stock is insufficient.')
            base_price = money(market_item.base_price * merchant.price_multiplier)
            quote = TradeService.quote(
                strategy_name=strategy_name,
                character=character,
                base_price=base_price,
                quantity=quantity,
            )
            if Decimal(character.coins) < quote.total_price:
                raise ValueError('Insufficient coins.')

            character.coins = int(Decimal(character.coins) - quote.total_price)
            character.save(update_fields=['coins', 'updated_at'])

            inventory_item, _ = InventoryItem.objects.select_for_update().get_or_create(
                character=character,
                item_name=market_item.name,
                defaults={'quantity': 0, 'avg_unit_price': money(0)},
            )
            old_qty = inventory_item.quantity
            new_qty = old_qty + quantity
            old_total = money(inventory_item.avg_unit_price * old_qty)
            new_total = old_total + quote.subtotal
            inventory_item.quantity = new_qty
            inventory_item.avg_unit_price = money(new_total / new_qty)
            inventory_item.save(update_fields=['quantity', 'avg_unit_price', 'updated_at'])

            merchant_inventory.stock = merchant_inventory.stock - quantity
            merchant_inventory.save(update_fields=['stock', 'updated_at'])

            return TradeOrder.objects.create(
                session=session,
                buyer=character,
                side=TradeOrder.SIDE_BUY,
                merchant_name=merchant.name,
                item_name=market_item.name,
                quantity=quantity,
                strategy=strategy_name,
                unit_price=quote.unit_price,
                subtotal=quote.subtotal,
                tax_amount=quote.tax_amount,
                total_price=quote.total_price,
                status=TradeOrder.STATUS_COMPLETED,
            )

        inventory_item = InventoryItem.objects.select_for_update().filter(
            character=character,
            item_name=market_item.name,
        ).first()
        if not inventory_item or inventory_item.quantity < quantity:
            raise ValueError('Insufficient item quantity to sell.')

        payout_unit = money(market_item.base_price * merchant.buyback_rate)
        if strategy_name == 'negotiation':
            payout_unit = money(payout_unit * Decimal('1.05'))
        elif strategy_name == 'barter':
            payout_unit = money(payout_unit * Decimal('1.02'))
        subtotal = money(payout_unit * quantity)
        tax_amount = money(0)
        total_price = subtotal

        character.coins = int(Decimal(character.coins) + total_price)
        character.save(update_fields=['coins', 'updated_at'])

        inventory_item.quantity = inventory_item.quantity - quantity
        if inventory_item.quantity == 0:
            inventory_item.delete()
        else:
            inventory_item.save(update_fields=['quantity', 'updated_at'])

        merchant_inventory.stock = merchant_inventory.stock + quantity
        merchant_inventory.save(update_fields=['stock', 'updated_at'])

        return TradeOrder.objects.create(
            session=session,
            buyer=character,
            side=TradeOrder.SIDE_SELL,
            merchant_name=merchant.name,
            item_name=market_item.name,
            quantity=quantity,
            strategy=strategy_name,
            unit_price=payout_unit,
            subtotal=subtotal,
            tax_amount=tax_amount,
            total_price=total_price,
            status=TradeOrder.STATUS_COMPLETED,
        )
