from accounts.signals import broadcast_to_company
from django.conf import settings
from django.contrib import admin
from django.utils.html import format_html

from .models import Category, Customer, Floor, Order, OrderItem, Product, Table, TableBooking, TableSession


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'phone', 'email', 'company', 'created_at')
    list_filter = ('company',)
    search_fields = ('name', 'phone', 'email')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'company', 'order')
    list_filter = ('company',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'kind', 'category', 'company', 'price',
        'stock_quantity', 'is_out_of_stock', 'show_in_menu', 'is_active',
    )
    list_filter = ('company', 'kind', 'show_in_menu', 'is_out_of_stock', 'is_active')
    search_fields = ('name', 'sku')


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'company', 'order')
    list_filter = ('company',)


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    """`qr_link` is the URL to encode into the physical QR sticker for this
    table — scanning it (or opening it directly) deep-links straight into the
    Zalo Mini App's /scan/<table_id> page, where a member can request to use
    this table with one tap (membership.api.RequestTableUseView).
    """

    list_display = ('id', 'name', 'floor', 'table_type', 'status', 'hourly_rate', 'is_active', 'qr_link')
    list_filter = ('floor__company', 'table_type', 'status')
    readonly_fields = ('qr_link',)

    @admin.display(description='Link QR yêu cầu dùng bàn')
    def qr_link(self, obj):
        if not settings.ZALO_APP_ID:
            return '(chưa cấu hình ZALO_APP_ID trong .env)'
        url = f'https://zalo.me/s/{settings.ZALO_APP_ID}/scan/{obj.pk}'
        return format_html('<a href="{0}" target="_blank">{0}</a>', url)


@admin.register(TableSession)
class TableSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'table', 'customer', 'status', 'guest_count', 'opened_at', 'closed_at', 'rental_amount', 'card_minutes_used')
    list_filter = ('status',)
    readonly_fields = ('opened_at',)


@admin.register(TableBooking)
class TableBookingAdmin(admin.ModelAdmin):
    """Until there's a real staff app, this is how the venue confirms/cancels
    member bookings — the actions below mirror store.api.BookingConfirmView /
    StaffBookingCancelView exactly (same status change + realtime push to the
    member), so editing `status` by hand here would skip the notification but
    these actions won't.
    """

    list_display = ('id', 'table', 'customer', 'start_time', 'duration_minutes', 'status', 'company')
    list_filter = ('company', 'status')
    search_fields = ('customer__name', 'customer__phone', 'table__name')
    actions = ('confirm_bookings', 'cancel_bookings')

    @admin.action(description='Xác nhận đặt bàn đã chọn')
    def confirm_bookings(self, request, queryset):
        from chat.utils import notify_customer

        from .services import confirm_booking

        count = 0
        opened = 0
        for booking in queryset.filter(status=TableBooking.PENDING).select_related('table', 'customer'):
            try:
                booking, session = confirm_booking(booking, request.user)
            except ValueError:
                continue
            notify_customer(booking.customer_id, {
                'event': 'booking_confirmed', 'booking_id': booking.pk, 'table_name': booking.table.name,
                'start_time': booking.start_time.isoformat(), 'opened_now': session is not None,
            })
            if session:
                broadcast_to_company(
                    booking.company, 'table_opened',
                    {'table_id': booking.table.pk, 'table_name': booking.table.name, 'floor_id': booking.table.floor_id, 'session_id': session.pk},
                    actor=request.user,
                    comment=f'{booking.table.name} được mở tự động do xác nhận đặt bàn của {booking.customer.name}.',
                )
                opened += 1
            count += 1
        message = f'Đã xác nhận {count} đặt bàn.'
        if opened:
            message += f' ({opened} bàn đã được mở ngay cho khách.)'
        self.message_user(request, message)

    @admin.action(description='Hủy đặt bàn đã chọn')
    def cancel_bookings(self, request, queryset):
        from django.utils import timezone

        from chat.utils import notify_customer

        count = 0
        for booking in queryset.exclude(status__in=(TableBooking.CANCELLED, TableBooking.COMPLETED)).select_related('table'):
            booking.status = TableBooking.CANCELLED
            booking.cancelled_at = timezone.now()
            booking.save(update_fields=['status', 'cancelled_at'])
            notify_customer(booking.customer_id, {
                'event': 'booking_cancelled', 'booking_id': booking.pk, 'table_name': booking.table.name,
            })
            count += 1
        self.message_user(request, f'Đã hủy {count} đặt bàn.')


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'product_name', 'unit_price', 'quantity')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    inlines = (OrderItemInline,)
    list_display = ('id', 'company', 'session', 'customer', 'status', 'created_at')
    list_filter = ('company', 'status')
    search_fields = ('customer__name', 'customer__phone')
