from django.db import transaction
from django.utils import timezone

from .models import ChatRoom, ChatRoomMember, Message

MAX_PINNED_ROOMS = 3


def get_or_create_direct_room(user_a, user_b):
    """Find the existing 1:1 room between two same-company users, or create one."""
    if user_a.company_id != user_b.company_id:
        raise ValueError('Users must belong to the same company.')

    existing = (
        ChatRoom.objects.filter(
            company_id=user_a.company_id, room_type=ChatRoom.DIRECT, members__user=user_a,
        )
        .filter(members__user=user_b)
        .first()
    )
    if existing:
        return existing, False

    with transaction.atomic():
        room = ChatRoom.objects.create(
            company_id=user_a.company_id, room_type=ChatRoom.DIRECT, created_by=user_a,
        )
        ChatRoomMember.objects.bulk_create([
            ChatRoomMember(room=room, user=user_a),
            ChatRoomMember(room=room, user=user_b),
        ])
    return room, True


def create_group_room(company, name, creator, member_users):
    with transaction.atomic():
        room = ChatRoom.objects.create(company=company, room_type=ChatRoom.GROUP, name=name, created_by=creator)
        members = {creator, *member_users}
        ChatRoomMember.objects.bulk_create([
            ChatRoomMember(room=room, user=u, role=ChatRoomMember.OWNER if u == creator else ChatRoomMember.MEMBER)
            for u in members
        ])
    return room


def mark_room_seen(room, user):
    """Record that `user` has viewed `room` up to now — used to compute unread counts."""
    ChatRoomMember.objects.filter(room=room, user=user).update(last_seen_at=timezone.now())


def unread_count(room, user):
    """How many messages in `room` (not sent by `user`) arrived after their last visit.

    Works for any room type — including the company-wide room, which every
    user gets a ChatRoomMember row for on account creation (see chat.signals).
    Returns 0 if there's no membership row at all (shouldn't normally happen).
    """
    member = ChatRoomMember.objects.filter(room=room, user=user).only('last_seen_at').first()
    if member is None:
        return 0
    qs = Message.objects.filter(room=room).exclude(sender=user)
    if member.last_seen_at:
        qs = qs.filter(created_at__gt=member.last_seen_at)
    return qs.count()


def total_unread_count(user):
    """Sum of unread messages across every room the user is in (including
    the company-wide room), skipping rooms they've muted.
    """
    total = 0
    members = ChatRoomMember.objects.filter(user=user, is_muted=False).select_related('room')
    for member in members:
        qs = Message.objects.filter(room=member.room).exclude(sender=user)
        if member.last_seen_at:
            qs = qs.filter(created_at__gt=member.last_seen_at)
        total += qs.count()
    return total


def set_room_muted(room, user, muted):
    ChatRoomMember.objects.filter(room=room, user=user).update(is_muted=muted)


def set_room_pinned(room, user, pinned):
    """Pin/unpin a room for `user`, capped at MAX_PINNED_ROOMS pinned rooms at once."""
    with transaction.atomic():
        if pinned:
            other_pinned_ids = list(
                ChatRoomMember.objects.select_for_update()
                .filter(user=user, is_pinned=True)
                .exclude(room=room)
                .values_list('id', flat=True)
            )
            if len(other_pinned_ids) >= MAX_PINNED_ROOMS:
                raise ValueError(f'Chỉ được ghim tối đa {MAX_PINNED_ROOMS} nhóm.')
        ChatRoomMember.objects.filter(room=room, user=user).update(is_pinned=pinned)


def set_member_role(room, target_user, role):
    """Promote/demote a group member between phó phòng (deputy) and thành
    viên (member). The owner itself can't be reassigned through this path.
    """
    if role not in (ChatRoomMember.DEPUTY, ChatRoomMember.MEMBER):
        raise ValueError('Vai trò không hợp lệ.')
    member = ChatRoomMember.objects.filter(room=room, user=target_user).first()
    if member is None:
        raise ValueError('Người dùng không phải thành viên của nhóm.')
    if member.role == ChatRoomMember.OWNER:
        raise ValueError('Không thể đổi vai trò của chủ phòng.')
    member.role = role
    member.save(update_fields=['role'])
    return member


def set_room_settings(room, chat_enabled=None, attachments_enabled=None, name=None, avatar=None):
    update_fields = []
    if chat_enabled is not None:
        room.chat_enabled = bool(chat_enabled)
        update_fields.append('chat_enabled')
    if attachments_enabled is not None:
        room.attachments_enabled = bool(attachments_enabled)
        update_fields.append('attachments_enabled')
    if name is not None:
        room.name = name
        update_fields.append('name')
    if avatar is not None:
        room.avatar = avatar
        update_fields.append('avatar')
    if update_fields:
        room.save(update_fields=update_fields)
    return room


def post_message(room, sender, content):
    """Persist a message. Delivery to viewers of this room happens over the
    RoomConsumer group (see chat/api.py + chat/consumers.py); recipients who
    aren't currently looking at the room rely on `unread_count` instead of a
    separate Notification — no need to double up on both.
    """
    message = Message.objects.create(room=room, sender=sender, content=content)
    ChatRoom.objects.filter(pk=room.pk).update(last_message_at=timezone.now())
    if sender is not None:
        mark_room_seen(room, sender)
    return message
