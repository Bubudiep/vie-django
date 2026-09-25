import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class CustomerToken(models.Model):
    """Opaque bearer token for a store.Customer logging into the member-facing
    Zalo Mini App. Not an oauth2_provider AccessToken (those authenticate
    accounts.User staff accounts) — this is a separate, simpler auth path.
    One row per customer; logging in again just rotates the key.
    """

    customer = models.OneToOneField('store.Customer', on_delete=models.CASCADE, related_name='auth_token')
    key = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = secrets.token_hex(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Token của {self.customer}'


class MembershipPlan(models.Model):
    """A purchasable time package (e.g. "Gói 10 giờ") — staff sells these in
    person/at the counter; buying one tops up the customer's MembershipCard.
    """

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='membership_plans')
    name = models.CharField(max_length=150)
    minutes = models.PositiveIntegerField('thời lượng (phút)')
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField('thứ tự', default=0)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return f'{self.name} ({self.minutes} phút)'


class MembershipCard(models.Model):
    """A customer's running prepaid-time balance. Table time on billiards/
    karaoke tables is deducted from `remaining_minutes` when their session
    closes (see store.services.close_table); a CardTransaction row is kept
    for every change so the balance is always auditable.
    """

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='membership_cards')
    customer = models.OneToOneField('store.Customer', on_delete=models.CASCADE, related_name='membership_card')
    remaining_minutes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at < timezone.now())

    def __str__(self):
        return f'Thẻ của {self.customer} - {self.remaining_minutes} phút'


class Event(models.Model):
    """A promotion/tournament/announcement shown on the member app's "Sự
    kiện" tab. Staff manage these through the admin; purely read-only content
    for members — no RSVP/registration flow (out of scope for now).
    """

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='events')
    title = models.CharField('tiêu đề', max_length=200)
    description = models.TextField('mô tả', blank=True)
    image = models.ImageField('ảnh', upload_to='events/%Y/%m/', null=True, blank=True)
    start_time = models.DateTimeField('bắt đầu', null=True, blank=True)
    end_time = models.DateTimeField('kết thúc', null=True, blank=True)
    is_active = models.BooleanField('hiển thị', default=True)
    order = models.PositiveIntegerField('thứ tự', default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', '-start_time', '-pk']

    def __str__(self):
        return f'{self.title} ({self.company})'


class PointsAccount(models.Model):
    """A customer's loyalty-points balance — a separate currency from
    MembershipCard's prepaid minutes. Earned automatically from spending
    (store.services.close_table) and from opening a table (visit bonus), or
    granted by staff by hand; spent via PointsRedemptionOption (see
    membership.services.redeem_points, which tops up MembershipCard minutes).
    """

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='points_accounts')
    customer = models.OneToOneField('store.Customer', on_delete=models.CASCADE, related_name='points_account')
    balance = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Điểm của {self.customer} - {self.balance}'


class PointsTransaction(models.Model):
    EARN_SPEND = 'earn_spend'
    EARN_VISIT = 'earn_visit'
    EARN_MANUAL = 'earn_manual'
    REDEEM = 'redeem'
    ADJUST = 'adjust'
    KIND_CHOICES = [
        (EARN_SPEND, 'Tích lũy từ chi tiêu'),
        (EARN_VISIT, 'Thưởng lượt ghé quán'),
        (EARN_MANUAL, 'Nhân viên cộng tay'),
        (REDEEM, 'Đổi điểm'),
        (ADJUST, 'Điều chỉnh'),
    ]

    account = models.ForeignKey(PointsAccount, on_delete=models.CASCADE, related_name='transactions')
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    points = models.IntegerField(help_text='Dương = cộng, âm = trừ.')
    session = models.ForeignKey('store.TableSession', on_delete=models.SET_NULL, null=True, blank=True, related_name='points_transactions')
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']

    def __str__(self):
        return f'{self.get_kind_display()} {self.points} điểm - {self.account}'


class PointsRedemptionOption(models.Model):
    """A "quy đổi" tier staff configure — e.g. "Đổi 30 phút chơi" for 100
    points. Redeeming tops up the member's MembershipCard by `minutes_reward`.
    """

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='points_redemption_options')
    label = models.CharField(max_length=150)
    points_cost = models.PositiveIntegerField()
    minutes_reward = models.PositiveIntegerField('phút được cộng')
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField('thứ tự', default=0)

    class Meta:
        ordering = ['order', 'points_cost']

    def __str__(self):
        return f'{self.label} ({self.points_cost} điểm)'


class Voucher(models.Model):
    """A promo template staff define, then assign to individual members as
    CustomerVoucher — vouchers here are venue-issued only, never bought with
    points (that's PointsRedemptionOption instead).
    """

    FIXED = 'fixed'
    PERCENT = 'percent'
    DISCOUNT_TYPE_CHOICES = [
        (FIXED, 'Giảm số tiền cố định'),
        (PERCENT, 'Giảm theo phần trăm'),
    ]

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='vouchers')
    title = models.CharField(max_length=150)
    description = models.CharField(max_length=255, blank=True)
    discount_type = models.CharField(max_length=10, choices=DISCOUNT_TYPE_CHOICES, default=FIXED)
    discount_value = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text='Số tiền (đ) nếu giảm cố định, hoặc số % (0-100) nếu giảm theo phần trăm.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class CustomerVoucher(models.Model):
    ACTIVE = 'active'
    USED = 'used'
    EXPIRED = 'expired'
    STATUS_CHOICES = [
        (ACTIVE, 'Còn hiệu lực'),
        (USED, 'Đã dùng'),
        (EXPIRED, 'Hết hạn'),
    ]

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='customer_vouchers')
    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name='assignments')
    customer = models.ForeignKey('store.Customer', on_delete=models.CASCADE, related_name='vouchers')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    used_session = models.ForeignKey('store.TableSession', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']

    @property
    def is_usable(self):
        return self.status == self.ACTIVE and not (self.expires_at and self.expires_at < timezone.now())

    def __str__(self):
        return f'{self.voucher.title} - {self.customer} ({self.get_status_display()})'


class CardTransaction(models.Model):
    TOPUP = 'topup'
    CONSUME = 'consume'
    ADJUST = 'adjust'
    KIND_CHOICES = [
        (TOPUP, 'Nạp giờ'),
        (CONSUME, 'Sử dụng'),
        (ADJUST, 'Điều chỉnh'),
    ]

    card = models.ForeignKey(MembershipCard, on_delete=models.CASCADE, related_name='transactions')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    minutes = models.DecimalField(max_digits=10, decimal_places=2, help_text='Dương = cộng, âm = trừ.')
    plan = models.ForeignKey(MembershipPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    session = models.ForeignKey('store.TableSession', on_delete=models.SET_NULL, null=True, blank=True, related_name='card_transactions')
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']

    def __str__(self):
        return f'{self.get_kind_display()} {self.minutes} phút - {self.card}'
