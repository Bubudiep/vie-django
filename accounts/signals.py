import logging

from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from chat.utils import notify_company, notify_user

from .models import Company, CompanyConfig, Notification, Profile, Role, get_or_create_system_account

logger = logging.getLogger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
        logger.info('Profile created for user_id=%s', instance.pk)


@receiver(pre_save, sender=settings.AUTH_USER_MODEL)
def track_password_change(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        old_password = sender.objects.get(pk=instance.pk).password
    except sender.DoesNotExist:
        return
    if old_password != instance.password:
        instance.must_change_password = False
        logger.info('Password changed for user_id=%s', instance.pk)


@receiver(post_save, sender=Company)
def create_default_roles(sender, instance, created, **kwargs):
    if created:
        Role.objects.bulk_create([
            Role(company=instance, name=name, display_name=display_name)
            for name, display_name in Role.DEFAULT_ROLES
        ])
        logger.info('Default roles created for company_id=%s', instance.pk)


def _company_payload(company):
    return {
        'id': company.id,
        'name': company.name,
        'business_code': company.business_code,
        'service_type': company.service_type,
        'plan_id': company.plan_id,
        'contact_name': company.contact_name,
        'contact_email': company.contact_email,
        'contact_phone': company.contact_phone,
        'address': company.address,
    }


EVENT_TITLES = {
    'company_updated': 'Thông tin công ty',
    'config_updated': 'Cấu hình công ty',
    'order_created': 'Đơn hàng mới',
    'order_status_changed': 'Cập nhật đơn hàng',
    'table_opened': 'Mở bàn/phòng',
    'table_closed': 'Đóng bàn/phòng',
    'booking_created': 'Đặt bàn mới',
    'booking_confirmed': 'Xác nhận đặt bàn',
    'booking_cancelled': 'Hủy đặt bàn',
    'payment_requested': 'Yêu cầu thanh toán',
    'voucher_assigned': 'Nhận voucher mới',
    'voucher_used': 'Sử dụng voucher',
}


def broadcast_to_company(company, event, extra, actor=None, comment=None):
    """Send a public notification to everyone currently in the company's room.

    `actor` is the real user who made the change (e.g. the admin editing the
    Company form); falls back to the company's system account when the
    change wasn't attributable to a specific user (e.g. an automated job).
    """
    updated_by = actor or get_or_create_system_account(company)
    title = EVENT_TITLES.get(event, event)
    if comment is None:
        comment = "Chưa có thông tin."
        if event == "company_updated":
            comment = f'Thông tin công ty được cập nhật bởi <user id={updated_by.id}>{updated_by.username}</user>'
    Notification.objects.create(
        company=company, event=event, title=title, comment=comment, payload=extra, is_public=True,
    )
    notify_company(company.id, {'event': event, 'title': title, 'comment': comment, **extra})
    logger.info('Broadcast %s: company_id=%s updated_by=%s', event, company.pk, updated_by.username)


def send_user_notification(user, event, extra, comment=''):
    """Send a private notification to a single user (not visible to their company-mates)."""
    system_user = get_or_create_system_account(user.company)
    title = EVENT_TITLES.get(event, event)
    Notification.objects.create(
        company=user.company, event=event, title=title, comment=comment, payload=extra,
        is_public=False, target=user,
    )
    notify_user(user.pk, {'event': event, 'title': title, 'comment': comment, **extra})
    logger.info('Notify %s: user_id=%s via system_user_id=%s', event, user.pk, system_user.pk)


@receiver(post_save, sender=Company)
def notify_company_updated(sender, instance, created, **kwargs):
    if created:
        return
    actor = getattr(instance, '_updated_by', None)
    broadcast_to_company(instance, 'company_updated', {'company': _company_payload(instance)}, actor=actor)


@receiver(post_save, sender=CompanyConfig)
def notify_config_updated(sender, instance, created, **kwargs):
    if created:
        return
    actor = getattr(instance, '_updated_by', None)
    broadcast_to_company(instance.company, 'config_updated', {'data': instance.data}, actor=actor)
