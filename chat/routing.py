from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r'^ws/room/(?P<company_id>[A-Za-z0-9]+)/$', consumers.ChatConsumer.as_asgi()),
    re_path(r'^ws/chat/(?P<room_id>\d+)/$', consumers.RoomConsumer.as_asgi()),
]
