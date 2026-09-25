from django.conf import settings
from django.db import models
from django.db.models.functions import Coalesce


class ChatRoomQuerySet(models.QuerySet):
    def for_user(self, user):
        """Every room a user can see: their company's room + any direct/group room they're a member of."""
        return self.filter(
            models.Q(company_id=user.company_id, room_type=ChatRoom.COMPANY)
            | models.Q(members__user=user)
        ).distinct()

    def annotate_pinned(self, user):
        """Adds `is_pinned_by_me` so callers can sort pinned rooms first without an N+1 per room."""
        pinned_subquery = ChatRoomMember.objects.filter(room=models.OuterRef('pk'), user=user).values('is_pinned')[:1]
        return self.annotate(
            is_pinned_by_me=Coalesce(
                models.Subquery(pinned_subquery, output_field=models.BooleanField()),
                models.Value(False),
                output_field=models.BooleanField(),
            ),
        )


class ChatRoom(models.Model):
    COMPANY = 'company'
    DIRECT = 'direct'
    GROUP = 'group'
    ROOM_TYPE_CHOICES = [
        (COMPANY, 'Toàn công ty'),
        (DIRECT, 'Nhắn tin riêng'),
        (GROUP, 'Nhóm'),
    ]

    objects = ChatRoomQuerySet.as_manager()

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='chat_rooms')
    room_type = models.CharField(max_length=10, choices=ROOM_TYPE_CHOICES)
    name = models.CharField(max_length=255, blank=True)
    avatar = models.ImageField(upload_to='chat_room_avatars/%Y/%m/', null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Denormalized so "list my rooms sorted by recent activity" never has to
    # aggregate over the (large, ever-growing) Message table.
    last_message_at = models.DateTimeField(null=True, blank=True)
    # Group-only moderation switches — enforced in RoomMessagesView.create().
    chat_enabled = models.BooleanField(
        'cho phép chat', default=True,
        help_text='Tắt: chỉ chủ/phó phòng được nhắn tin (chế độ chỉ thông báo).',
    )
    attachments_enabled = models.BooleanField(
        'cho phép gửi đính kèm', default=True,
        help_text='Tắt: chỉ chủ/phó phòng được gửi file/link.',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['company'],
                condition=models.Q(room_type='company'),
                name='unique_company_room_per_company',
            ),
        ]
        indexes = [
            models.Index(fields=['company', '-last_message_at'], name='chatroom_company_recent_idx'),
        ]

    def __str__(self):
        return self.name or f'{self.get_room_type_display()} ({self.company})'


class ChatRoomMember(models.Model):
    OWNER = 'owner'
    DEPUTY = 'deputy'
    MEMBER = 'member'
    ROLE_CHOICES = [
        (OWNER, 'Chủ phòng'),
        (DEPUTY, 'Phó phòng'),
        (MEMBER, 'Thành viên'),
    ]

    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_room_memberships')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, help_text='Lần cuối user xem tin nhắn của room này.')
    is_muted = models.BooleanField('tắt thông báo', default=False)
    is_pinned = models.BooleanField('ghim', default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['room', 'user'], name='unique_room_member'),
        ]
        indexes = [
            models.Index(fields=['user', 'room'], name='chatroommember_user_room_idx'),
        ]

    def __str__(self):
        return f'{self.user} in {self.room}'


class Message(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+',
    )
    content = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']
        indexes = [
            # Cursor pagination for "latest messages in this room" — the one
            # query pattern that has to stay fast once a room has millions
            # of rows; a plain FK index on room_id alone can't satisfy the
            # ORDER BY without an extra sort, this composite index can.
            models.Index(fields=['room', '-id'], name='message_room_recent_idx'),
        ]

    def __str__(self):
        return f'Message#{self.pk} in room {self.room_id}'


class Attachment(models.Model):
    FILE = 'file'
    LINK = 'link'
    KIND_CHOICES = [(FILE, 'File'), (LINK, 'Link')]

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='attachments')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    file = models.FileField(upload_to='chat_attachments/%Y/%m/', null=True, blank=True)
    url = models.URLField(blank=True)
    name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveBigIntegerField(null=True, blank=True)
    # A tiny blurred base64 data URI for image attachments (see chat.images),
    # so the client can paint an instant placeholder before `file` loads.
    preview_data_url = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name or self.url or f'Attachment#{self.pk}'
