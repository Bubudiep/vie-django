from django.urls import path

from . import views
from .api import (
    DirectRoomView,
    GroupCreateView,
    MuteRoomView,
    PinRoomView,
    RoomAttachmentsView,
    RoomLinksView,
    RoomListView,
    RoomMemberRoleView,
    RoomMembersView,
    RoomMessagesView,
    RoomSettingsView,
)

app_name = 'chat'
urlpatterns = [
    path('', views.company_room, name='room'),
    path('api/rooms/', RoomListView.as_view(), name='rooms'),
    path('api/rooms/group/', GroupCreateView.as_view(), name='rooms-group'),
    path('api/rooms/direct/', DirectRoomView.as_view(), name='rooms-direct'),
    path('api/rooms/<int:room_id>/messages/', RoomMessagesView.as_view(), name='room-messages'),
    path('api/rooms/<int:room_id>/mute/', MuteRoomView.as_view(), name='room-mute'),
    path('api/rooms/<int:room_id>/pin/', PinRoomView.as_view(), name='room-pin'),
    path('api/rooms/<int:room_id>/settings/', RoomSettingsView.as_view(), name='room-settings'),
    path('api/rooms/<int:room_id>/members/', RoomMembersView.as_view(), name='room-members'),
    path('api/rooms/<int:room_id>/members/<int:user_id>/role/', RoomMemberRoleView.as_view(), name='room-member-role'),
    path('api/rooms/<int:room_id>/attachments/', RoomAttachmentsView.as_view(), name='room-attachments'),
    path('api/rooms/<int:room_id>/links/', RoomLinksView.as_view(), name='room-links'),
]
