from decimal import Decimal

from django.conf import settings
from django.db import models


class Category(models.Model):
    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='product_categories')
    name = models.CharField(max_length=150)
    order = models.PositiveIntegerField('thứ tự', default=0)

    class Meta:
        ordering = ['order', 'name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_category_name_per_company'),
        ]

    def __str__(self):
        return self.name


class Product(models.Model):
    GOODS = 'goods'
    FOOD = 'food'
    DRINK = 'drink'
    KIND_CHOICES = [
        (GOODS, 'Hàng hóa'),
        (FOOD, 'Món ăn'),
        (DRINK, 'Nước uống'),
    ]

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='products')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=GOODS)
    name = models.CharField(max_length=255)
    unit = models.CharField('đơn vị tính', max_length=50, blank=True, default='cái')
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sku = models.CharField('mã sản phẩm', max_length=100, blank=True)
    image = models.FileField(upload_to='products/%Y/%m/', null=True, blank=True)
    track_stock = models.BooleanField('quản lý tồn kho', default=False, help_text='Chỉ áp dụng cho hàng hóa, không dùng cho món ăn/nước uống.')
    stock_quantity = models.DecimalField('tồn kho', max_digits=12, decimal_places=2, default=0)
    is_out_of_stock = models.BooleanField(
        'hết hàng', default=False,
        help_text='Đánh dấu thủ công (vd. món hết nguyên liệu hôm nay) — với hàng có quản lý tồn kho thì tồn kho về 0 cũng tự tính là hết hàng.',
    )
    show_in_menu = models.BooleanField('hiển thị cho khách order', default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'sku'], condition=~models.Q(sku=''), name='unique_product_sku_per_company',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def in_stock(self):
        if self.is_out_of_stock:
            return False
        if self.track_stock:
            return self.stock_quantity > 0
        return True


class Floor(models.Model):
    """A physical floor/area of a venue (e.g. "Tầng 1", "Sân thượng") that tables belong to."""

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='floors')
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField('thứ tự', default=0)

    class Meta:
        ordering = ['order', 'name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_floor_name_per_company'),
        ]

    def __str__(self):
        return f'{self.name} ({self.company})'


class Table(models.Model):
    """A sellable spot on the floor plan: a dining table, a billiards table, or
    a karaoke room. `hourly_rate` turns on time-based billing for the latter two.
    """

    DINING = 'dining'
    BILLIARDS = 'billiards'
    KARAOKE = 'karaoke'
    OTHER = 'other'
    TABLE_TYPE_CHOICES = [
        (DINING, 'Bàn ăn'),
        (BILLIARDS, 'Bàn bi-a'),
        (KARAOKE, 'Phòng karaoke'),
        (OTHER, 'Khác'),
    ]

    AVAILABLE = 'available'
    OCCUPIED = 'occupied'
    RESERVED = 'reserved'
    CLEANING = 'cleaning'
    STATUS_CHOICES = [
        (AVAILABLE, 'Trống'),
        (OCCUPIED, 'Đang sử dụng'),
        (RESERVED, 'Đã đặt trước'),
        (CLEANING, 'Đang dọn dẹp'),
    ]

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='tables')
    floor = models.ForeignKey(Floor, on_delete=models.CASCADE, related_name='tables')
    name = models.CharField(max_length=100)
    table_type = models.CharField(max_length=10, choices=TABLE_TYPE_CHOICES, default=DINING)
    capacity = models.PositiveIntegerField('sức chứa', default=4)
    hourly_rate = models.DecimalField(
        'giá thuê theo giờ', max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Áp dụng cho bàn bi-a / phòng karaoke. Để trống nếu không tính tiền theo giờ.',
    )
    # Floor-plan layout — a simple canvas the frontend can position/resize
    # this table on; units are whatever the frontend's canvas uses (px or %).
    pos_x = models.FloatField('vị trí X', default=0)
    pos_y = models.FloatField('vị trí Y', default=0)
    width = models.FloatField(default=1)
    height = models.FloatField(default=1)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=AVAILABLE)
    is_active = models.BooleanField(default=True)
    camera_url = models.URLField(
        'link camera bàn', max_length=500, blank=True,
        help_text='Link stream (HLS .m3u8) hoặc trang embed của camera gắn tại bàn này — dùng cho nút "Check VAR" trên app hội viên. Để trống nếu bàn chưa lắp camera.',
    )

    class Meta:
        ordering = ['floor__order', 'name']
        constraints = [
            models.UniqueConstraint(fields=['floor', 'name'], name='unique_table_name_per_floor'),
        ]

    def __str__(self):
        return f'{self.name} - {self.floor}'


class TableSession(models.Model):
    """One occupancy of a table, from open to close. For hourly-rated tables
    (billiards/karaoke) this is also the billing clock; for plain dining
    tables it's just a way to group orders under one visit.
    """

    OPEN = 'open'
    CLOSED = 'closed'
    STATUS_CHOICES = [(OPEN, 'Đang mở'), (CLOSED, 'Đã đóng')]

    table = models.ForeignKey(Table, on_delete=models.PROTECT, related_name='sessions')
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+',
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    guest_count = models.PositiveIntegerField('số khách', default=1)
    customer = models.ForeignKey(
        'Customer', on_delete=models.SET_NULL, null=True, blank=True, related_name='table_sessions',
        help_text='Hội viên đang ngồi bàn này, nếu có — dùng để trừ giờ thẻ hội viên khi đóng phiên.',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=OPEN)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    rental_amount = models.DecimalField(
        'tiền thuê bàn', max_digits=12, decimal_places=2, default=0,
        help_text='Tính từ hourly_rate khi đóng phiên, sau khi trừ phần đã trả bằng giờ thẻ hội viên (nếu có).',
    )
    card_minutes_used = models.DecimalField(
        'số phút trừ từ thẻ hội viên', max_digits=10, decimal_places=2, default=0,
    )

    class Meta:
        ordering = ['-opened_at']
        constraints = [
            models.UniqueConstraint(fields=['table'], condition=models.Q(status='open'), name='unique_open_session_per_table'),
        ]

    def __str__(self):
        return f'Session#{self.pk} - {self.table}'


class TableBooking(models.Model):
    """A member's advance reservation of a table for a future time — separate
    from TableSession, which is the actual live occupancy clock. Staff
    confirms/cancels; when the member arrives, staff opens the table as usual
    (optionally attaching this same customer) and the booking is left as-is
    for the record.
    """

    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    CANCELLED = 'cancelled'
    COMPLETED = 'completed'
    STATUS_CHOICES = [
        (PENDING, 'Chờ xác nhận'),
        (CONFIRMED, 'Đã xác nhận'),
        (CANCELLED, 'Đã hủy'),
        (COMPLETED, 'Đã nhận bàn'),
    ]

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='table_bookings')
    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name='bookings')
    customer = models.ForeignKey('Customer', on_delete=models.CASCADE, related_name='bookings')
    start_time = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=60)
    note = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-start_time']
        indexes = [models.Index(fields=['company', 'table', 'start_time'])]

    @property
    def end_time(self):
        from datetime import timedelta
        return self.start_time + timedelta(minutes=self.duration_minutes)

    def __str__(self):
        return f'{self.table} - {self.customer} @ {self.start_time:%Y-%m-%d %H:%M}'


class Customer(models.Model):
    """A shop's own customer record — independent of accounts.User, since a
    walk-in/phone customer doesn't necessarily have a login account."""

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='customers')
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'phone'], condition=~models.Q(phone=''), name='unique_customer_phone_per_company',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.phone})' if self.phone else self.name


class Order(models.Model):
    PENDING = 'pending'
    SERVED = 'served'
    CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (PENDING, 'Đang xử lý'),
        (SERVED, 'Đã phục vụ'),
        (CANCELLED, 'Đã hủy'),
    ]

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='orders')
    session = models.ForeignKey(
        TableSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders',
        help_text='Để trống nếu là đơn mang về / không gắn bàn.',
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders',
        help_text='Khách hàng đặt đơn, để trống nếu là khách vãng lai không lưu thông tin.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']
        indexes = [models.Index(fields=['company', 'customer'])]

    def __str__(self):
        return f'Order#{self.pk}'

    @property
    def total_amount(self):
        return sum((item.total_price for item in self.items.all()), Decimal('0'))


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='+')
    # Snapshots so a later price/name edit on Product doesn't rewrite history.
    product_name = models.CharField(max_length=255)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)

    @property
    def total_price(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f'{self.quantity} x {self.product_name}'
