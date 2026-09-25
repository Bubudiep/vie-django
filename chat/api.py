import logging
import re

from accounts.models import User
from accounts.permissions import MatchesCompanyHeader
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView, ListCreateAPIView
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .images import process_image
from .models import Attachment, ChatRoom, ChatRoomMember, Message
from .permissions import get_member_role, is_room_admin, is_room_member
from .serializers import (
    DirectRoomSerializer,
    GroupCreateSerializer,
    MessageCreateSerializer,
    MessageSerializer,
    RoomAttachmentSerializer,
    RoomMemberSerializer,
    RoomSerializer,
)
from .services import (
    create_group_room,
    get_or_create_direct_room,
    mark_room_seen,
    post_message,
    set_member_role,
    set_room_muted,
    set_room_pinned,
    set_room_settings,
    unread_count,
)
from .utils import notify_room

logger = logging.getLogger(__name__)


class RoomListView(ListAPIView):
    """Every room the current user can see: their company room + their direct/group rooms."""

    serializer_class = RoomSerializer
    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get_queryset(self):
        return (
            ChatRoom.objects.for_user(self.request.user)
            .select_related('company')
            .annotate_pinned(self.request.user)
            .order_by('-is_pinned_by_me', '-last_message_at', '-created_at')
        )


class GroupCreateView(APIView):
    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, *args, **kwargs):
        serializer = GroupCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        members = User.objects.filter(
            pk__in=serializer.validated_data['member_ids'], company_id=request.user.company_id,
        )
        room = create_group_room(request.user.company, serializer.validated_data['name'], request.user, members)
        logger.info('Group room created: room_id=%s by user_id=%s', room.pk, request.user.pk)
        return Response(RoomSerializer(room, context={'request': request}).data, status=201)


class DirectRoomView(APIView):
    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, *args, **kwargs):
        serializer = DirectRoomSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        other = get_object_or_404(
            User, pk=serializer.validated_data['user_id'], company_id=request.user.company_id,
        )
        if other.pk == request.user.pk:
            raise PermissionDenied('Không thể tự nhắn tin cho chính mình.')
        room, created = get_or_create_direct_room(request.user, other)
        return Response(RoomSerializer(room, context={'request': request}).data, status=201 if created else 200)


class MuteRoomView(APIView):
    """Toggle whether the current user gets notified about a room — including
    the company-wide room (e.g. muting it over the weekend).
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, room_id, *args, **kwargs):
        room = get_object_or_404(ChatRoom, pk=room_id)
        if not is_room_member(room, request.user):
            raise PermissionDenied('Bạn không phải thành viên của room này.')
        muted = bool(request.data.get('muted', True))
        set_room_muted(room, request.user, muted)
        return Response({'room_id': room.pk, 'is_muted': muted})


class PinRoomView(APIView):
    """Pin/unpin a room for the current user, capped at MAX_PINNED_ROOMS pinned at once."""

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, room_id, *args, **kwargs):
        room = get_object_or_404(ChatRoom, pk=room_id)
        if not is_room_member(room, request.user):
            raise PermissionDenied('Bạn không phải thành viên của room này.')
        pinned = bool(request.data.get('pinned', True))
        try:
            set_room_pinned(room, request.user, pinned)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        return Response({'room_id': room.pk, 'is_pinned': pinned})


class RoomMessagesPagination(CursorPagination):
    page_size = 30
    max_page_size = 100
    ordering = '-id'


class RoomMessagesView(ListCreateAPIView):
    """GET: cursor-paginated message history for a room. POST: send a message
    (text, and/or a single link or file attachment), persisted then pushed
    live to anyone connected to this room's WebSocket group.
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)
    pagination_class = RoomMessagesPagination

    def get_room(self):
        room = get_object_or_404(ChatRoom, pk=self.kwargs['room_id'])
        if not is_room_member(room, self.request.user):
            raise PermissionDenied('Bạn không phải thành viên của room này.')
        return room

    def get_serializer_class(self):
        return MessageCreateSerializer if self.request.method == 'POST' else MessageSerializer

    def get_queryset(self):
        room = self.get_room()
        return Message.objects.filter(room=room).select_related('sender').prefetch_related('attachments')

    def list(self, request, *args, **kwargs):
        room = self.get_room()
        # Snapshot unread count before marking the room seen, so the caller
        # can still tell "you had N unread" even though this same GET is
        # what marks the room as read.
        unread = unread_count(room, request.user)
        response = super().list(request, *args, **kwargs)
        mark_room_seen(room, request.user)
        response.data['unread_count'] = unread
        return response

    def create(self, request, *args, **kwargs):
        room = self.get_room()
        serializer = MessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        admin = is_room_admin(room, request.user)
        if not room.chat_enabled and not admin:
            raise PermissionDenied('Nhóm đã tắt chat, chỉ chủ/phó phòng được nhắn tin.')
        if (data.get('file') or data.get('link')) and not room.attachments_enabled and not admin:
            raise PermissionDenied('Nhóm đã tắt gửi đính kèm.')

        message = post_message(room, request.user, data.get('content', ''))

        uploaded_file = data.get('file')
        link = data.get('link')
        if uploaded_file:
            content_type = getattr(uploaded_file, 'content_type', '') or ''
            file_to_store, name, size, preview_data_url = uploaded_file, uploaded_file.name, uploaded_file.size, ''

            if content_type.startswith('image/'):
                processed, preview_data_url = process_image(uploaded_file, uploaded_file.name)
                if processed is not None:
                    file_to_store, name, content_type = processed, processed.name, 'image/jpeg'
                    size = file_to_store.size

            Attachment.objects.create(
                message=message, kind=Attachment.FILE, file=file_to_store,
                name=name, size=size, content_type=content_type, preview_data_url=preview_data_url,
            )
        elif link:
            Attachment.objects.create(message=message, kind=Attachment.LINK, url=link, name=link)

        out = MessageSerializer(message, context={'request': request}).data
        notify_room(room.id, out)
        logger.info('Message sent: room_id=%s sender_id=%s message_id=%s', room.pk, request.user.pk, message.pk)
        return Response(out, status=201)


def _get_member_room(room_id, user):
    """Shared lookup for the info-panel endpoints below: 404 if the room
    doesn't exist, 403 if the caller isn't a member of it."""
    room = get_object_or_404(ChatRoom, pk=room_id)
    if not is_room_member(room, user):
        raise PermissionDenied('Bạn không phải thành viên của room này.')
    return room


class RoomMembersView(ListAPIView):
    """Everyone in a room, for the chat info panel's "Thành viên" tab."""

    serializer_class = RoomMemberSerializer
    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get_queryset(self):
        room = _get_member_room(self.kwargs['room_id'], self.request.user)
        return (
            ChatRoomMember.objects.filter(room=room)
            .select_related('user', 'user__role', 'user__profile')
            .order_by('user__username')
        )


class RoomAttachmentsPagination(CursorPagination):
    page_size = 30
    max_page_size = 100
    ordering = '-id'


class RoomAttachmentsView(ListAPIView):
    """Every file shared in a room, for the info panel's "File" tab."""

    serializer_class = RoomAttachmentSerializer
    permission_classes = (IsAuthenticated, MatchesCompanyHeader)
    pagination_class = RoomAttachmentsPagination

    def get_queryset(self):
        room = _get_member_room(self.kwargs['room_id'], self.request.user)
        return (
            Attachment.objects.filter(message__room=room, kind=Attachment.FILE)
            .select_related('message__sender')
        )


class RoomMemberRoleView(APIView):
    """Chủ phòng promotes/demotes a group member to phó phòng (deputy) or back to thành viên."""

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, room_id, user_id, *args, **kwargs):
        room = _get_member_room(room_id, request.user)
        if room.room_type != ChatRoom.GROUP:
            raise PermissionDenied('Chỉ áp dụng vai trò chủ/phó phòng cho nhóm.')
        if get_member_role(room, request.user) != ChatRoomMember.OWNER:
            raise PermissionDenied('Chỉ chủ phòng được đổi vai trò thành viên.')
        target = get_object_or_404(User, pk=user_id, company_id=request.user.company_id)
        role = request.data.get('role')
        try:
            member = set_member_role(room, target, role)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        logger.info(
            'Room role changed: room_id=%s target_user_id=%s role=%s by user_id=%s',
            room.pk, target.pk, role, request.user.pk,
        )
        return Response({'room_id': room.pk, 'user_id': target.pk, 'role': member.role})


class RoomSettingsView(APIView):
    """Chủ/phó phòng toggles group settings, and renames the group or changes
    its avatar."""

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, room_id, *args, **kwargs):
        room = _get_member_room(room_id, request.user)
        if room.room_type != ChatRoom.GROUP:
            raise PermissionDenied('Chỉ áp dụng cho nhóm.')
        if not is_room_admin(room, request.user):
            raise PermissionDenied('Chỉ chủ/phó phòng được đổi cài đặt nhóm.')

        name = request.data.get('name')
        if name is not None:
            name = name.strip()
            if not name:
                raise ValidationError('Tên nhóm không được để trống.')

        avatar_upload = request.data.get('avatar')
        avatar_to_store = None
        if avatar_upload:
            content_type = getattr(avatar_upload, 'content_type', '') or ''
            if not content_type.startswith('image/'):
                raise ValidationError('Ảnh đại diện phải là file ảnh.')
            processed, _ = process_image(avatar_upload, avatar_upload.name)
            avatar_to_store = processed if processed is not None else avatar_upload

        room = set_room_settings(
            room,
            chat_enabled=request.data.get('chat_enabled'),
            attachments_enabled=request.data.get('attachments_enabled'),
            name=name,
            avatar=avatar_to_store,
        )
        logger.info(
            'Room settings changed: room_id=%s chat_enabled=%s attachments_enabled=%s name=%r avatar=%s by user_id=%s',
            room.pk, room.chat_enabled, room.attachments_enabled, room.name, bool(avatar_to_store), request.user.pk,
        )
        return Response(RoomSerializer(room, context={'request': request}).data)


LINK_RE = re.compile(r'(?:https?://|www\.)[^\s<]+', re.IGNORECASE)
LINK_TRAILING_PUNCT_RE = re.compile(r'[.,!?;:)\]}\'"]+$')
MAX_ROOM_LINKS = 100


class RoomLinksView(APIView):
    """Every link found in a room's message text, for the info panel's "Link"
    tab. Links aren't stored separately (they're typed inline in a message,
    same as the frontend auto-linkifies them) so this scans recent message
    content rather than querying a dedicated table.
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get(self, request, room_id, *args, **kwargs):
        room = _get_member_room(room_id, request.user)
        messages = (
            Message.objects.filter(room=room)
            .exclude(content='')
            .select_related('sender')
            .only('id', 'content', 'created_at', 'sender__username')[:500]
        )

        links = []
        for message in messages:
            for match in LINK_RE.finditer(message.content):
                url = LINK_TRAILING_PUNCT_RE.sub('', match.group(0))
                links.append({
                    'message_id': message.pk,
                    'url': url,
                    'sender_username': message.sender.username if message.sender else None,
                    'created_at': message.created_at.isoformat(),
                })
                if len(links) >= MAX_ROOM_LINKS:
                    break
            if len(links) >= MAX_ROOM_LINKS:
                break

        return Response(links)
