from __future__ import annotations

from decimal import Decimal


class MarketRuleLayer:
    ALLOWED_RARITY = {'common', 'rare', 'epic'}

    @staticmethod
    def _normalize_name(name: str) -> str:
        return ' '.join(name.strip().split())

    @classmethod
    def sanitize_items(cls, raw_items: list[dict]) -> list[dict]:
        cleaned: list[dict] = []
        seen: set[str] = set()

        for item in raw_items or []:
            name = cls._normalize_name(str(item.get('name', '')))
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue

            rarity = str(item.get('rarity', 'common')).lower().strip()
            if rarity not in cls.ALLOWED_RARITY:
                rarity = 'common'

            category = str(item.get('category', 'misc')).strip()[:60]
            try:
                base_price = Decimal(str(item.get('base_price', '10')))
            except Exception:
                base_price = Decimal('10')

            # Guardrails for economy stability.
            if base_price < Decimal('1'):
                base_price = Decimal('1')
            if base_price > Decimal('10000'):
                base_price = Decimal('10000')

            stock = int(item.get('stock', 20) or 20)
            if stock < 1:
                stock = 1
            if stock > 9999:
                stock = 9999

            cleaned.append(
                {
                    'name': name[:120],
                    'category': category,
                    'rarity': rarity,
                    'base_price': base_price,
                    'stock': stock,
                }
            )
            seen.add(key)

        if not cleaned:
            cleaned = [
                {'name': 'Traveler Ration', 'category': 'consumable', 'rarity': 'common', 'base_price': Decimal('8'), 'stock': 50},
                {'name': 'Torch Kit', 'category': 'tool', 'rarity': 'common', 'base_price': Decimal('12'), 'stock': 40},
                {'name': 'Ancient Shard', 'category': 'artifact', 'rarity': 'rare', 'base_price': Decimal('120'), 'stock': 8},
            ]

        return cleaned

    @classmethod
    def sanitize_merchants(cls, raw_merchants: list[dict]) -> list[dict]:
        cleaned: list[dict] = []
        seen: set[str] = set()

        for merchant in raw_merchants or []:
            name = cls._normalize_name(str(merchant.get('name', '')))
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue

            location = cls._normalize_name(str(merchant.get('location', 'Central Market')))[:120]
            try:
                multiplier = Decimal(str(merchant.get('price_multiplier', '1.00')))
            except Exception:
                multiplier = Decimal('1.00')
            try:
                buyback = Decimal(str(merchant.get('buyback_rate', '0.60')))
            except Exception:
                buyback = Decimal('0.60')

            if multiplier < Decimal('0.70'):
                multiplier = Decimal('0.70')
            if multiplier > Decimal('1.60'):
                multiplier = Decimal('1.60')

            if buyback < Decimal('0.20'):
                buyback = Decimal('0.20')
            if buyback > Decimal('0.90'):
                buyback = Decimal('0.90')

            cleaned.append(
                {
                    'name': name[:120],
                    'location': location,
                    'price_multiplier': multiplier,
                    'buyback_rate': buyback,
                }
            )
            seen.add(key)

        if not cleaned:
            cleaned = [
                {
                    'name': 'Quartermaster Rowan',
                    'location': 'Central Market',
                    'price_multiplier': Decimal('1.00'),
                    'buyback_rate': Decimal('0.60'),
                }
            ]

        return cleaned
