from django.contrib import admin

from .models import (
    CardTransaction,
    CustomerToken,
    CustomerVoucher,
    Event,
    MembershipCard,
    MembershipPlan,
    PointsAccount,
    PointsRedemptionOption,
    PointsTransaction,
    Voucher,
)


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'minutes', 'price', 'company', 'is_active', 'order')
    list_filter = ('company', 'is_active')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'company', 'start_time', 'end_time', 'is_active', 'order')
    list_filter = ('company', 'is_active')
    search_fields = ('title',)


class CardTransactionInline(admin.TabularInline):
    model = CardTransaction
    extra = 1
    fields = ('kind', 'minutes', 'plan', 'session', 'note', 'created_by', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(MembershipCard)
class MembershipCardAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'company', 'remaining_minutes', 'expires_at', 'updated_at')
    list_filter = ('company',)
    search_fields = ('customer__name', 'customer__phone')
    inlines = (CardTransactionInline,)


@admin.register(CustomerToken)
class CustomerTokenAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'created_at')
    search_fields = ('customer__name', 'customer__phone')


class PointsTransactionInline(admin.TabularInline):
    """Add a row with kind=Nhân viên cộng tay to grant points manually —
    same pattern as CardTransactionInline for membership-card minutes."""

    model = PointsTransaction
    extra = 1
    fields = ('kind', 'points', 'note', 'created_by', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(PointsAccount)
class PointsAccountAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'company', 'balance', 'updated_at')
    list_filter = ('company',)
    search_fields = ('customer__name', 'customer__phone')
    inlines = (PointsTransactionInline,)


@admin.register(PointsRedemptionOption)
class PointsRedemptionOptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'label', 'points_cost', 'minutes_reward', 'company', 'is_active', 'order')
    list_filter = ('company', 'is_active')


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'discount_type', 'discount_value', 'company', 'is_active')
    list_filter = ('company', 'is_active', 'discount_type')
    search_fields = ('title',)


@admin.register(CustomerVoucher)
class CustomerVoucherAdmin(admin.ModelAdmin):
    """Assigning one here (add + save) is how staff hands a member a promo
    voucher — pushes a realtime notification on creation, same idea as
    store.admin.TableBookingAdmin's confirm/cancel actions.
    """

    list_display = ('id', 'voucher', 'customer', 'company', 'status', 'expires_at', 'created_at')
    list_filter = ('company', 'status')
    search_fields = ('customer__name', 'customer__phone', 'voucher__title')
    exclude = ('company', 'assigned_by')

    def save_model(self, request, obj, form, change):
        is_new = obj.pk is None
        if is_new:
            obj.assigned_by = request.user
            obj.company = obj.voucher.company
        super().save_model(request, obj, form, change)
        if is_new:
            from chat.utils import notify_customer
            notify_customer(obj.customer_id, {
                'event': 'voucher_assigned', 'customer_voucher_id': obj.pk, 'voucher_title': obj.voucher.title,
            })
