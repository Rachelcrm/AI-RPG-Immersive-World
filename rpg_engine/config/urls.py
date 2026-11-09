from django.contrib import admin
from django.urls import include, path

from game.views import PlayPageView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('game.urls')),
    path('', PlayPageView.as_view(), name='play-page'),
]
