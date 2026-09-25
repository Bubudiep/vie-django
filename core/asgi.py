import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter

from accounts.channels_auth import OAuth2TokenAuthMiddleware
import chat.routing

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': OAuth2TokenAuthMiddleware(
        URLRouter(chat.routing.websocket_urlpatterns)
    ),
})
