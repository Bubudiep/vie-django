from rest_framework import serializers

from .models import Attachment, ChatRoom, Message


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ('id', 'kind', 'file', 'url', 'name', 'content_type', 'size', 'preview_data_url', 'created_at')
        read_only_fields = fields


class RoomAttachmentSerializer(AttachmentSerializer):
    """An attachment plus who sent it — for a room's shared-files list, where
    (unlike inside a message bubble) that context isn't otherwise implied."""

    sender_username = serializers.CharField(source='message.sender.username', read_only=True, default=None)

    class Meta(AttachmentSerializer.Meta):
        fields = AttachmentSerializer.Meta.fields + ('message_id', 'sender_username')


class RoomMemberSerializer(serializers.Serializer):
    id = serializers.IntegerField(source='user.id')
    username = serializers.CharField(source='user.username')
    role_name = serializers.CharField(source='user.role.name', default=None)
    avatar_url = serializers.CharField(source='user.profile.avatar_url', default='')
    # Chủ phòng / phó phòng / thành viên — distinct from role_name above,
    # which is the user's company-wide role (admin/staff/...).
    room_role = serializers.CharField(source='role')
    room_role_display = serializers.CharField(source='get_role_display')
    is_muted = serializers.BooleanField()
    joined_at = serializers.DateTimeField()


class MessageSerializer(serializers.ModelSerializer):
    attachments = AttachmentSerializer(many=True, read_only=True)
    sender_username = serializers.CharField(source='sender.username', read_only=True, default=None)

    class Meta:
        model = Message
        fields = ('id', 'room', 'sender', 'sender_username', 'content', 'attachments', 'created_at')
        read_only_fields = fields


class MessageCreateSerializer(serializers.Serializer):
    content = serializers.CharField(required=False, allow_blank=True, default='')
    link = serializers.URLField(required=False, allow_blank=True)
    file = serializers.FileField(required=False)

    def validate(self, attrs):
        if not attrs.get('content') and not attrs.get('link') and not attrs.get('file'):
            raise serializers.ValidationError('Cần có ít nhất content, link hoặc file.')
        return attrs


class RoomSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    is_muted = serializers.SerializerMethodField()
    is_pinned = serializers.SerializerMethodField()
    my_role = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = (
            'id', 'room_type', 'display_name', 'avatar_url', 'member_count', 'unread_count', 'is_muted',
            'is_pinned', 'my_role', 'chat_enabled', 'attachments_enabled', 'last_message', 'last_message_at',
            'created_at',
        )
        read_only_fields = fields

    def get_avatar_url(self, obj):
        if not obj.avatar:
            return None
        request = self.context.get('request')
        url = obj.avatar.url
        return request.build_absolute_uri(url) if request is not None else url

    def get_display_name(self, obj):
        if obj.room_type == ChatRoom.COMPANY:
            return obj.company.name
        if obj.room_type == ChatRoom.GROUP:
            return obj.name
        request = self.context.get('request')
        if request is not None:
            other = obj.members.exclude(user_id=request.user.pk).select_related('user').first()
            if other:
                return other.user.username
        return obj.name

    def get_member_count(self, obj):
        if obj.room_type == ChatRoom.COMPANY:
            return obj.company.users.count()
        return obj.members.count()

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request is None:
            return None
        from .services import unread_count
        return unread_count(obj, request.user)

    def get_is_muted(self, obj):
        request = self.context.get('request')
        if request is None:
            return False
        member = obj.members.filter(user=request.user).only('is_muted').first()
        return member.is_muted if member else False

    def get_is_pinned(self, obj):
        # Reuse the annotation from ChatRoomQuerySet.annotate_pinned when the
        # list view already computed it, instead of a query per room.
        if hasattr(obj, 'is_pinned_by_me'):
            return bool(obj.is_pinned_by_me)
        request = self.context.get('request')
        if request is None:
            return False
        member = obj.members.filter(user=request.user).only('is_pinned').first()
        return member.is_pinned if member else False

    def get_my_role(self, obj):
        request = self.context.get('request')
        if request is None or obj.room_type == ChatRoom.COMPANY:
            return None
        member = obj.members.filter(user=request.user).only('role').first()
        return member.role if member else None

    def get_last_message(self, obj):
        # Message.Meta.ordering is ['-pk'], so .first() is the latest one.
        message = obj.messages.select_related('sender').first()
        if message is None:
            return None
        return {
            'id': message.pk,
            'sender_id': message.sender_id,
            'sender_username': message.sender.username if message.sender else None,
            'content': message.content[:200],
            'created_at': message.created_at.isoformat(),
        }


class GroupCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    member_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class DirectRoomSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
