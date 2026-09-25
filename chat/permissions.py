from rest_framework.permissions import BasePermission

from .models import ChatRoom, ChatRoomMember


def is_room_member(room, user):
    if not getattr(user, 'is_authenticated', False):
        return False
    if room.room_type == ChatRoom.COMPANY:
        return room.company_id == user.company_id
    return ChatRoomMember.objects.filter(room=room, user=user).exists()


def get_member_role(room, user):
    """None for the company-wide room (no owner/deputy concept there) or a non-member."""
    if not getattr(user, 'is_authenticated', False) or room.room_type == ChatRoom.COMPANY:
        return None
    member = ChatRoomMember.objects.filter(room=room, user=user).only('role').first()
    return member.role if member else None


def is_room_admin(room, user):
    """Chủ phòng (owner) or phó phòng (deputy) — the two roles allowed to
    moderate a group room (toggle chat/attachments, manage member roles).
    """
    return get_member_role(room, user) in (ChatRoomMember.OWNER, ChatRoomMember.DEPUTY)


class IsRoomMember(BasePermission):
    message = 'Bạn không phải thành viên của room này.'

    def has_object_permission(self, request, view, room):
        return is_room_member(room, request.user)
