import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import Company, User

from .models import ChatRoom, ChatRoomMember

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Company)
def create_company_room(sender, instance, created, **kwargs):
    if created:
        ChatRoom.objects.create(company=instance, room_type=ChatRoom.COMPANY, name=instance.name)
        logger.info('Company room created for company_id=%s', instance.pk)


@receiver(post_save, sender=User)
def add_user_to_company_room(sender, instance, created, **kwargs):
    """Give every new user a ChatRoomMember row in their company's room, so
    unread/mute tracking (which relies on that row) works for it too, not
    just direct/group rooms.
    """
    if not created or not instance.company_id:
        return
    room = ChatRoom.objects.filter(company_id=instance.company_id, room_type=ChatRoom.COMPANY).first()
    if room:
        ChatRoomMember.objects.get_or_create(room=room, user=instance)
