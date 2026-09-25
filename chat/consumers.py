import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .utils import room_group_name

logger = logging.getLogger(__name__)

BACKLOG_SIZE = 20


@database_sync_to_async
def _recent_notifications(user_id):
    from accounts.models import Notification, User

    user = User.objects.only('id', 'date_joined', 'company_id').get(pk=user_id)
    qs = Notification.objects.visible_to(user)[:BACKLOG_SIZE]
    return [
        {
            'id': n.pk,
            'event': n.event,
            'title': n.title,
            'comment': n.comment,
            'payload': n.payload,
            'is_public': n.is_public,
            'created_at': n.created_at.isoformat(),
        }
        for n in qs
    ]


class ChatConsumer(AsyncWebsocketConsumer):
    """One public room per company, named after the company's own id, plus a
    private per-user group for notifications targeted at just one person.

    The URL carries the company id so the room is addressable/debuggable,
    but a connection is only accepted if it matches the authenticated user's
    own company (from the OAuth2 token) — a user can never join another
    company's room, regardless of what id they put in the URL.
    """

    async def connect(self):
        user = self.scope['user']
        requested_company_id = self.scope['url_route']['kwargs']['company_id']

        if not user.is_authenticated or not getattr(user, 'company_id', None):
            logger.warning('WebSocket rejected: unauthenticated or no company (user=%r)', user)
            await self.close(code=4401)
            return

        if requested_company_id != user.company_id:
            logger.warning(
                'WebSocket rejected: user_id=%s company_id=%r tried to join room %r',
                user.pk, user.company_id, requested_company_id,
            )
            await self.close(code=4403)
            return

        # Staff (accounts.User) get the full presence/backlog experience below;
        # members (membership.principals.CustomerPrincipal, wrapping a
        # store.Customer) just get the company room + their own private group —
        # UserSession/Notification.visible_to() are staff-only concepts.
        self.principal_kind = getattr(user, 'principal_kind', 'user')
        self.user_id = user.pk
        self.company_id = user.company_id
        self.room_group_name = self.company_id
        self.personal_group_name = f'{self.principal_kind}_{self.user_id}'

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.channel_layer.group_add(self.personal_group_name, self.channel_name)
        await self.accept()
        logger.info('WebSocket connected: %s_id=%s company_id=%r', self.principal_kind, user.pk, self.company_id)

        if self.principal_kind != 'user':
            await self.send(text_data=json.dumps({'type': 'backlog', 'items': []}))
            return

        backlog = await _recent_notifications(self.user_id)
        await self.send(text_data=json.dumps({'type': 'backlog', 'items': backlog}))

        from accounts.presence import online_users, register_session

        session_count = await database_sync_to_async(register_session)(user, self.channel_name)
        online = await database_sync_to_async(online_users)(self.company_id)
        await self.send(text_data=json.dumps({'type': 'presence_list', 'users': online}))

        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'presence_event', 'event': 'join', 'user_id': self.user_id, 'session_count': session_count},
        )

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
            await self.channel_layer.group_discard(self.personal_group_name, self.channel_name)
            logger.info('WebSocket disconnected: company_id=%r code=%s', self.company_id, close_code)

            if getattr(self, 'principal_kind', 'user') != 'user':
                return

            from accounts.presence import unregister_session

            user_id, remaining = await database_sync_to_async(unregister_session)(self.channel_name)
            if user_id is not None:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {'type': 'presence_event', 'event': 'leave', 'user_id': user_id, 'session_count': remaining},
                )

    async def notification(self, event):
        await self.send(text_data=json.dumps({'type': 'notification', 'payload': event['payload']}))

    async def presence_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'presence',
            'event': event['event'],
            'user_id': event['user_id'],
            'session_count': event['session_count'],
        }))


@database_sync_to_async
def _check_room_membership(user, room_id):
    from .models import ChatRoom
    from .permissions import is_room_member

    try:
        room = ChatRoom.objects.get(pk=room_id)
    except ChatRoom.DoesNotExist:
        return False
    return is_room_member(room, user)


@database_sync_to_async
def _save_message(room_id, user, content):
    from .models import ChatRoom
    from .serializers import MessageSerializer
    from .services import post_message

    room = ChatRoom.objects.get(pk=room_id)
    message = post_message(room, user, content)
    return MessageSerializer(message).data


@database_sync_to_async
def _mark_seen(room_id, user):
    from .models import ChatRoom
    from .services import mark_room_seen

    room = ChatRoom.objects.get(pk=room_id)
    mark_room_seen(room, user)


class RoomConsumer(AsyncWebsocketConsumer):
    """Live messages for one specific chat room (company/direct/group).

    Separate from ChatConsumer (presence + notifications, one connection per
    user for their whole company session): a client opens one of these for
    whichever room(s) it wants live updates for — the room currently open,
    plus (for a chat home screen) one per other room just to keep unread
    counts live — and every message, whether sent here or through the REST
    API, is persisted first and then relayed to this group, so REST and
    WebSocket clients always agree.

    Connecting here does NOT mark the room as read — a client may hold a
    connection open for a room it isn't actually looking at (see above), so
    that would incorrectly clear its unread count. Only the REST message
    history endpoint (``RoomMessagesView``) does that, since fetching it is
    what "viewing" a room actually means — plus an explicit client-sent
    ``{"type": "mark_seen"}`` ping, which the actively-open ChatWindow (never
    the background/unread-tracking connections) sends each time a live
    message arrives, so last_seen_at keeps advancing while someone is
    watching the room in real time instead of only at the moment it opened.
    """

    async def connect(self):
        user = self.scope['user']
        room_id = self.scope['url_route']['kwargs']['room_id']

        if not user.is_authenticated:
            logger.warning('Room WS rejected: unauthenticated')
            await self.close(code=4401)
            return

        allowed = await _check_room_membership(user, room_id)
        if not allowed:
            logger.warning('Room WS rejected: user_id=%s not a member of room_id=%s', user.pk, room_id)
            await self.close(code=4403)
            return

        self.room_id = room_id
        self.group_name = room_group_name(room_id)

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info('Room WS connected: user_id=%s room_id=%s', user.pk, room_id)

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            logger.info('Room WS disconnected: room_id=%s code=%s', self.room_id, close_code)

    async def receive(self, text_data):
        data = json.loads(text_data)
        user = self.scope['user']

        if data.get('type') == 'mark_seen':
            await _mark_seen(self.room_id, user)
            return

        content = data.get('message', '')
        message = await _save_message(self.room_id, user, content)
        await self.channel_layer.group_send(
            self.group_name,
            {'type': 'chat_message', 'message': message},
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({'type': 'message', 'message': event['message']}))
