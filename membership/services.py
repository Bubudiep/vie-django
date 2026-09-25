import secrets
from decimal import Decimal

import requests
from django.conf import settings
from django.db import transaction

from .models import CardTransaction, CustomerToken, MembershipCard, PointsAccount, PointsRedemptionOption, PointsTransaction

# 1 điểm mỗi 10.000đ thực chi (tiền bàn + tiền món, sau khi đã trừ phần trả
# bằng thẻ hội viên) khi đóng bàn; xem store.services.close_table.
POINTS_PER_VND_SPENT = Decimal('10000')
# Điểm thưởng mỗi lượt mở bàn (visit bonus); xem store.services.open_table.
VISIT_BONUS_POINTS = 5


def resolve_zalo_phone(zalo_access_token, phone_token):
    """Exchange the Zalo Mini App getPhoneNumber() token for the user's real
    phone number via Zalo's server-to-server API (single-use, expires after
    2 minutes — see https://docs.zaloplatforms.com/docs/MA/api/user/user-information/getPhoneNumber).
    `zalo_access_token` is the *user's* token from the client-side
    getAccessToken() call; `secret_key` is the venue's Mini App secret,
    never sent from the frontend.
    """
    if not settings.ZALO_APP_SECRET:
        raise ValueError('Server chưa cấu hình ZALO_APP_SECRET.')

    response = requests.get(
        'https://graph.zalo.me/v2.0/me/info',
        headers={'access_token': zalo_access_token, 'code': phone_token, 'secret_key': settings.ZALO_APP_SECRET},
        timeout=10,
    )
    data = response.json()
    if data.get('error'):
        raise ValueError(data.get('message') or 'Không lấy được số điện thoại từ Zalo.')

    number = (data.get('data') or {}).get('number', '')
    if not number:
        raise ValueError('Zalo không trả về số điện thoại.')

    # Zalo returns international format ("849xxxxxxxx") — normalize to the
    # local "09xxxxxxxx" format the rest of the app (store.Customer) uses.
    if number.startswith('84'):
        number = '0' + number[2:]
    return number


def customer_login(company, phone, name=''):
    """Find-or-create a store.Customer by phone under `company` and (re)issue
    their CustomerToken. Logging in again from a new device simply rotates
    the key. `phone` should already be a verified number — see
    resolve_zalo_phone for how membership.api.CustomerLoginView gets one.
    """
    from store.services import get_or_create_customer

    customer = get_or_create_customer(company, phone, name)
    token, _ = CustomerToken.objects.get_or_create(customer=customer)
    token.key = secrets.token_hex(32)
    token.save(update_fields=['key'])
    return customer, token


def get_or_create_card(customer):
    card, _ = MembershipCard.objects.get_or_create(company=customer.company, customer=customer)
    return card


def topup_card(card, minutes, plan=None, note='', created_by=None):
    with transaction.atomic():
        card = MembershipCard.objects.select_for_update().get(pk=card.pk)
        card.remaining_minutes += Decimal(str(minutes))
        card.save(update_fields=['remaining_minutes', 'updated_at'])
        CardTransaction.objects.create(
            card=card, kind=CardTransaction.TOPUP, minutes=Decimal(str(minutes)),
            plan=plan, note=note, created_by=created_by,
        )
    return card


def consume_card_minutes(card, minutes, session=None, note=''):
    """Deduct up to `minutes` from the card (never below 0) and log it.
    Returns how many minutes were actually deducted.
    """
    minutes = Decimal(str(minutes))
    with transaction.atomic():
        card = MembershipCard.objects.select_for_update().get(pk=card.pk)
        used = min(minutes, card.remaining_minutes)
        if used <= 0:
            return Decimal('0')
        card.remaining_minutes -= used
        card.save(update_fields=['remaining_minutes', 'updated_at'])
        CardTransaction.objects.create(
            card=card, kind=CardTransaction.CONSUME, minutes=-used, session=session, note=note,
        )
    return used


def get_or_create_points_account(customer):
    account, _ = PointsAccount.objects.get_or_create(company=customer.company, customer=customer)
    return account


def earn_points(account, points, kind, session=None, note='', created_by=None):
    """Add `points` (always >= 0) to `account` and log it. No-op if points <= 0
    (e.g. a session with 0 spend earns nothing)."""
    if points <= 0:
        return account
    with transaction.atomic():
        account = PointsAccount.objects.select_for_update().get(pk=account.pk)
        account.balance += points
        account.save(update_fields=['balance', 'updated_at'])
        PointsTransaction.objects.create(
            account=account, kind=kind, points=points, session=session, note=note, created_by=created_by,
        )
    return account


def earn_points_for_spend(customer, amount_spent, session=None):
    """Spend-based earn: floor(amount_spent / POINTS_PER_VND_SPENT) points."""
    points = int(Decimal(amount_spent) // POINTS_PER_VND_SPENT)
    if points <= 0:
        return
    account = get_or_create_points_account(customer)
    earn_points(account, points, PointsTransaction.EARN_SPEND, session=session, note=f'Chi tiêu {amount_spent:,.0f}đ')


def earn_points_for_visit(customer):
    account = get_or_create_points_account(customer)
    earn_points(account, VISIT_BONUS_POINTS, PointsTransaction.EARN_VISIT, note='Mở bàn')


def redeem_points(account, option: PointsRedemptionOption):
    """Spend `option.points_cost` points for `option.minutes_reward` minutes
    on the member's MembershipCard. Raises ValueError if the balance is short.
    """
    with transaction.atomic():
        account = PointsAccount.objects.select_for_update().get(pk=account.pk)
        if account.balance < option.points_cost:
            raise ValueError('Bạn không đủ điểm để đổi.')
        account.balance -= option.points_cost
        account.save(update_fields=['balance', 'updated_at'])
        PointsTransaction.objects.create(
            account=account, kind=PointsTransaction.REDEEM, points=-option.points_cost,
            note=f'Đổi: {option.label}',
        )
        card = get_or_create_card(account.customer)
        topup_card(card, option.minutes_reward, note=f'Quy đổi từ điểm thưởng: {option.label}')
    return account
