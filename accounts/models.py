import secrets
import string
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import models
from oauth2_provider.settings import oauth2_settings

def generate_company_id():
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(18))

class Plan(models.Model):
    name = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_users = models.PositiveIntegerField(null=True, blank=True, help_text='Để trống = không giới hạn số user.')
    description = models.TextField(blank=True)
    def __str__(self):
        return self.name

class Company(models.Model):
    SERVICE_TYPE_CHOICES = [
        ('retail', 'Bán lẻ'),
        ('restaurant', 'Nhà hàng'),
        ('wholesale', 'Bán buôn'),
        ('service', 'Dịch vụ'),
        ('other', 'Khác'),
    ]

    id = models.CharField(primary_key=True, max_length=18, default=generate_company_id, editable=False)
    name = models.CharField(max_length=255)
    business_code = models.CharField('mã số thuế / mã kinh doanh', max_length=50, unique=True, null=True, blank=True)
    service_type = models.CharField(max_length=20, choices=SERVICE_TYPE_CHOICES, blank=True)
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, related_name='companies', null=True, blank=True)

    contact_name = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class CompanyConfig(models.Model):
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='config')
    data = models.JSONField('cấu hình', default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Config của {self.company}'

class NotificationQuerySet(models.QuerySet):
    def visible_to(self, user):
        # Only notifications created after the account existed — a new user
        # shouldn't see a backlog of things that happened before they joined.
        return self.filter(company_id=user.company_id, created_at__gte=user.date_joined).filter(
            models.Q(is_public=True) | models.Q(target_id=user.pk)
        )

class Notification(models.Model):
    objects = NotificationQuerySet.as_manager()

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='notifications')
    event = models.CharField(max_length=100)
    title = models.CharField('tiêu đề', max_length=255, default='')
    comment = models.TextField('ghi chú', blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    is_public = models.BooleanField(
        'công khai toàn công ty',
        default=True,
        help_text='True: gửi cho cả công ty. False: chỉ gửi riêng cho user ở field target.',
    )
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='targeted_notifications',
        null=True,
        blank=True,
        help_text='User nhận riêng, chỉ có ý nghĩa khi is_public=False.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']
        indexes = [models.Index(fields=['company', '-id'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(is_public=True, target__isnull=True) | models.Q(is_public=False, target__isnull=False),
                name='notification_target_matches_is_public',
            ),
        ]

    def __str__(self):
        return f'{self.title} ({self.company})'

class Role(models.Model):
    ADMIN = 'admin'
    STAFF = 'staff'
    TESTER = 'tester'
    SYSTEM = 'system'
    DEFAULT_ROLES = [
        (ADMIN, 'Quản trị viên'),
        (STAFF, 'Nhân viên'),
        (TESTER, 'Kiểm thử viên'),
        (SYSTEM, 'Hệ thống'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='roles')
    name = models.CharField(max_length=100)
    display_name = models.CharField('tên hiển thị', max_length=100, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_role_name_per_company'),
        ]

    def __str__(self):
        return f'{self.display_name or self.name} ({self.company})'

class User(AbstractUser):
    username = models.CharField(
        'username',
        max_length=150,
        help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.',
        validators=[UnicodeUsernameValidator()],
    )
    application = models.ForeignKey(
        oauth2_settings.APPLICATION_MODEL,
        on_delete=models.CASCADE,
        related_name='users',
        null=True,
        blank=True,
        help_text='OAuth2 client application this user registered through.',
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name='users',
        null=True,
        blank=True,
        help_text='Customer company this user belongs to.',
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.SET_NULL,
        related_name='users',
        null=True,
        blank=True,
        help_text='Vai trò của user trong company. Phải thuộc cùng company với user.',
    )
    department = models.ForeignKey(
        'Department',
        on_delete=models.SET_NULL,
        related_name='members',
        null=True,
        blank=True,
        help_text='Phòng ban của user. Phải thuộc cùng company với user.',
    )
    position = models.ForeignKey(
        'Position',
        on_delete=models.SET_NULL,
        related_name='holders',
        null=True,
        blank=True,
        help_text='Chức vụ của user. Phải thuộc cùng company với user.',
    )
    must_change_password = models.BooleanField(
        'phải đổi mật khẩu',
        default=True,
        help_text='True nếu user chưa từng tự đổi mật khẩu ban đầu (do admin cấp).',
    )
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['username', 'company'], name='unique_username_per_company'),
            models.UniqueConstraint(
                fields=['username'],
                condition=models.Q(company__isnull=True),
                name='unique_username_without_company',
            ),
        ]

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        if self.role_id and self.role.company_id != self.company_id:
            raise ValidationError({'role': 'Role phải thuộc cùng company với user.'})
        if self.department_id and self.department.company_id != self.company_id:
            raise ValidationError({'department': 'Phòng ban phải thuộc cùng company với user.'})
        if self.position_id and self.position.company_id != self.company_id:
            raise ValidationError({'position': 'Chức vụ phải thuộc cùng company với user.'})

    def __str__(self):
        return self.username

class NotificationRead(models.Model):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name='reads')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notification_reads')
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['notification', 'user'], name='unique_notification_read_per_user'),
        ]

    def __str__(self):
        return f'{self.user} read {self.notification_id}'

class UserSession(models.Model):
    """One row per live WebSocket connection, used to compute who is online."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sessions')
    channel_name = models.CharField(max_length=255, unique=True)
    connected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user} @ {self.channel_name}'

def get_or_create_system_account(company):
    """Return the company's system account, creating it (and its role) if missing."""
    role, _ = Role.objects.get_or_create(
        company=company,
        name=Role.SYSTEM,
        defaults={'display_name': dict(Role.DEFAULT_ROLES)[Role.SYSTEM]},
    )
    user, created = User.objects.get_or_create(
        company=company,
        username='system',
        defaults={'role': role, 'is_active': False},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
    return user

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    display_name = models.CharField('tên hiển thị', max_length=150, blank=True)
    facebook_url = models.URLField('link facebook', blank=True)
    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField('ảnh đại diện', upload_to='avatars/%Y/%m/', null=True, blank=True)
    # Blurred base64 placeholder for `avatar`, built the same way as chat
    # attachment previews (see chat.images.process_image) — instant paint
    # while the real avatar is still loading on a slow connection.
    avatar_preview_data_url = models.TextField(blank=True)
    avatar_url = models.URLField(blank=True, help_text='Ảnh đại diện ngoài (vd: từ mạng xã hội), dùng khi chưa upload avatar.')
    cover = models.ImageField('ảnh bìa', upload_to='profile_covers/%Y/%m/', null=True, blank=True)
    address = models.CharField(max_length=255, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    bio = models.TextField('ghi chú cá nhân', blank=True)

    def __str__(self):
        return f'Profile của {self.user.username}'


class BankCard(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bank_cards')
    bank_name = models.CharField('tên ngân hàng', max_length=150, blank=True)
    bin_code = models.CharField('mã BIN ngân hàng', max_length=10)
    account_holder = models.CharField('chủ tài khoản', max_length=150)
    account_number = models.CharField('số tài khoản', max_length=50)
    is_primary = models.BooleanField('thẻ chính', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['user', 'bin_code', 'account_number'], name='unique_bank_card_per_user'),
        ]

    def __str__(self):
        return f'{self.bank_name or self.bin_code} - {self.account_number} ({self.user})'


class Department(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='departments')
    name = models.CharField('tên phòng ban', max_length=150)
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, related_name='children', null=True, blank=True,
        help_text='Phòng ban cấp trên, để trống nếu là phòng ban gốc.',
    )
    head = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name='headed_departments', null=True, blank=True,
        help_text='Trưởng phòng.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_department_name_per_company'),
        ]
        indexes = [models.Index(fields=['company', 'parent'])]

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        if self.parent_id:
            if self.parent.company_id != self.company_id:
                raise ValidationError({'parent': 'Phòng ban cha phải thuộc cùng company.'})
            node = self.parent
            while node is not None:
                if node.pk == self.pk:
                    raise ValidationError({'parent': 'Không thể tạo vòng lặp phòng ban.'})
                node = node.parent
        if self.head_id and self.head.company_id != self.company_id:
            raise ValidationError({'head': 'Trưởng phòng phải thuộc cùng company.'})

    def __str__(self):
        return f'{self.name} ({self.company})'


class Position(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='positions')
    name = models.CharField('chức vụ', max_length=150)
    level = models.PositiveIntegerField(
        'cấp bậc', default=0, help_text='Số càng nhỏ càng cao trong sơ đồ tổ chức (0 = cao nhất).',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['level', 'name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_position_name_per_company'),
        ]

    def __str__(self):
        return f'{self.name} ({self.company})'
