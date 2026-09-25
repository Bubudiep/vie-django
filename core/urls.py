from oauth2_provider import urls as oauth2_urls
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('chat/', include('chat.urls')),
    path('accounts/', include('accounts.urls')),
    path('store/', include('store.urls')),
    path('inventory/', include('inventory.urls')),
    path('membership/', include('membership.urls')),
    path('o2/', include(oauth2_urls)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
