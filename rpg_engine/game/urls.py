from django.urls import path

from .views import (
    AITradeView,
    BookUploadView,
    CharacterCreateView,
    HealthView,
    MarketBootstrapView,
    SessionInteractView,
    SessionStartView,
    TradeExecuteView,
    TradeQuoteView,
    WorldGenerateView,
)

urlpatterns = [
    path('health/', HealthView.as_view(), name='health'),
    path('books/upload/', BookUploadView.as_view(), name='book-upload'),
    path('worlds/generate/', WorldGenerateView.as_view(), name='world-generate'),
    path('characters/create/', CharacterCreateView.as_view(), name='character-create'),
    path('sessions/start/', SessionStartView.as_view(), name='session-start'),
    path('sessions/<int:session_id>/interact/', SessionInteractView.as_view(), name='session-interact'),
    path('market/bootstrap/', MarketBootstrapView.as_view(), name='market-bootstrap'),
    path('trades/quote/', TradeQuoteView.as_view(), name='trade-quote'),
    path('trades/execute/', TradeExecuteView.as_view(), name='trade-execute'),
    path('trades/ai-act/', AITradeView.as_view(), name='trade-ai-act'),
]
