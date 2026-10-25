from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from game.models import Book, Character, MarketItem, Merchant, MerchantInventory, StorySession, World


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def book(db):
    return Book.objects.create(title='demo-book', content='Once upon a time in a ruined kingdom...')


@pytest.fixture
def world(book):
    return World.objects.create(
        book=book,
        name='Ashen Realm',
        source_book_title=book.title,
        lore_summary='A kingdom fallen to ash.',
        factions=['Ember Guard', 'Grey Monks'],
        locations=['Ruin Hall', 'Ash Market'],
        main_conflict='Who controls the last flame.',
    )


@pytest.fixture
def character(world):
    return Character.objects.create(world=world, name='Kai', role='Ranger', coins=100)


@pytest.fixture
def session(world, character):
    return StorySession.objects.create(world=world, character=character, title='Demo Adventure', status='active')


@pytest.fixture
def merchant(world):
    return Merchant.objects.create(
        world=world,
        name='Old Pell',
        location='Ash Market',
        price_multiplier=Decimal('1.00'),
        buyback_rate=Decimal('0.60'),
    )


@pytest.fixture
def market_item(world, merchant):
    item = MarketItem.objects.create(world=world, name='Traveler Ration', category='food', base_price=Decimal('10.00'))
    MerchantInventory.objects.create(merchant=merchant, market_item=item, stock=5)
    return item
