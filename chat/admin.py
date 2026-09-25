from django.contrib import admin

from .models import Attachment, ChatRoom, ChatRoomMember, Message


class ChatRoomMemberInline(admin.TabularInline):
    model = ChatRoomMember
    extra = 0
    readonly_fields = ('joined_at',)


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    inlines = (ChatRoomMemberInline,)
    list_display = ('id', 'room_type', 'name', 'company', 'last_message_at', 'created_at')
    list_filter = ('room_type', 'company')
    readonly_fields = ('created_at', 'last_message_at')


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    readonly_fields = ('kind', 'file', 'url', 'name', 'content_type', 'size', 'created_at')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    inlines = (AttachmentInline,)
    list_display = ('id', 'room', 'sender', 'content', 'created_at')
    list_filter = ('room__company',)
    readonly_fields = ('room', 'sender', 'content', 'created_at')

    def has_add_permission(self, request):
        return False
