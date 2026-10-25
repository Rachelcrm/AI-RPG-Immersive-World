from decimal import Decimal

import pytest

from game.models import InventoryItem, TradeOrder
from game.services.trade_service import (
    BarterStrategy,
    CurrencyManager,
    FixedPriceStrategy,
    NegotiationStrategy,
    TradeService,
    TradeStrategyFactory,
)


def test_currency_manager_is_singleton():
    assert CurrencyManager() is CurrencyManager()
    assert CurrencyManager().base_currency == 'GOLD'


def test_currency_manager_tax_rounds_to_cents():
    assert CurrencyManager().compute_tax(Decimal('10.00')) == Decimal('0.50')
    assert CurrencyManager().compute_tax(Decimal('0.01')) == Decimal('0.00')


@pytest.mark.parametrize(
    'name, cls',
    [('fixed', FixedPriceStrategy), ('negotiation', NegotiationStrategy), ('barter', BarterStrategy)],
)
def test_strategy_factory_creates_each_strategy(name, cls):
    assert isinstance(TradeStrategyFactory.create(name), cls)


def test_strategy_factory_rejects_unknown():
    with pytest.raises(ValueError):
        TradeStrategyFactory.create('bribe')


def test_negotiation_discount_depends_on_role_and_quantity(character):
    base = Decimal('100.00')
    assert NegotiationStrategy().unit_price(base_price=base, character=character, quantity=1) == Decimal('96.00')
    assert NegotiationStrategy().unit_price(base_price=base, character=character, quantity=10) == Decimal('93.00')

    character.role = 'Merchant'
    assert NegotiationStrategy().unit_price(base_price=base, character=character, quantity=1) == Decimal('90.00')


def test_quote_applies_strategy_and_tax(character):
    quote = TradeService.quote(strategy_name='barter', character=character, base_price=Decimal('10.00'), quantity=2)
    assert quote.unit_price == Decimal('8.50')
    assert quote.subtotal == Decimal('17.00')
    assert quote.tax_amount == Decimal('0.85')
    assert quote.total_price == Decimal('17.85')


def test_execute_deducts_coins_and_adds_inventory(session, character):
    order = TradeService.execute(
        session_id=session.id,
        character_id=character.id,
        item_name='Moon Shard',
        quantity=2,
        base_price=Decimal('12.50'),
        strategy_name='fixed',
    )
    character.refresh_from_db()
    assert order.status == TradeOrder.STATUS_COMPLETED
    assert order.total_price == Decimal('26.25')
    # coins are integer; the fractional part is truncated
    assert character.coins == 73
    inv = InventoryItem.objects.get(character=character, item_name='Moon Shard')
    assert inv.quantity == 2
    assert inv.avg_unit_price == Decimal('12.50')


def test_execute_rejects_insufficient_coins(session, character):
    with pytest.raises(ValueError, match='Insufficient coins'):
        TradeService.execute(
            session_id=session.id,
            character_id=character.id,
            item_name='Dragon Egg',
            quantity=1,
            base_price=Decimal('999.00'),
            strategy_name='fixed',
        )
    character.refresh_from_db()
    assert character.coins == 100
    assert not InventoryItem.objects.filter(character=character).exists()


def test_market_buy_then_sell_round_trip(session, character, merchant, market_item):
    buy = TradeService.execute_market_trade(
        session_id=session.id,
        character_id=character.id,
        merchant_id=merchant.id,
        item_name='traveler ration',  # case-insensitive match
        quantity=2,
        action='buy',
        strategy_name='fixed',
    )
    character.refresh_from_db()
    assert buy.side == TradeOrder.SIDE_BUY
    assert buy.item_name == 'Traveler Ration'
    assert buy.total_price == Decimal('21.00')
    assert character.coins == 79
    assert merchant.inventory.get(market_item=market_item).stock == 3

    sell = TradeService.execute_market_trade(
        session_id=session.id,
        character_id=character.id,
        merchant_id=merchant.id,
        item_name='Traveler Ration',
        quantity=2,
        action='sell',
        strategy_name='fixed',
    )
    character.refresh_from_db()
    assert sell.side == TradeOrder.SIDE_SELL
    assert sell.total_price == Decimal('12.00')  # 10.00 * 0.60 * 2
    assert character.coins == 91
    assert merchant.inventory.get(market_item=market_item).stock == 5
    assert not InventoryItem.objects.filter(character=character).exists()


def test_market_buy_rejects_out_of_stock(session, character, merchant, market_item):
    with pytest.raises(ValueError, match='stock'):
        TradeService.execute_market_trade(
            session_id=session.id,
            character_id=character.id,
            merchant_id=merchant.id,
            item_name='Traveler Ration',
            quantity=99,
            action='buy',
            strategy_name='fixed',
        )
