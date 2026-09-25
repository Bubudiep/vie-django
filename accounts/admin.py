from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import CompanyUserCreationForm
from .models import BankCard, Company, CompanyConfig, Department, Notification, Plan, Position, Profile, Role, User, UserSession


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'max_users')


class CompanyConfigInline(admin.StackedInline):
    model = CompanyConfig
    can_delete = False


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    inlines = (CompanyConfigInline,)
    list_display = ('id', 'name', 'business_code', 'service_type', 'plan', 'contact_email', 'created_at')
    list_filter = ('service_type', 'plan')
    readonly_fields = ('id', 'created_at')

    def save_model(self, request, obj, form, change):
        obj._updated_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            instance._updated_by = request.user
            instance.save()
        formset.save_m2m()


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('event', 'company', 'created_at')
    list_filter = ('event', 'company')
    readonly_fields = ('company', 'event', 'payload', 'created_at')

    def has_add_permission(self, request):
        return False


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'channel_name', 'connected_at')
    list_filter = ('user__company',)
    readonly_fields = ('user', 'channel_name', 'connected_at')

    def has_add_permission(self, request):
        return False


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_name', 'company')
    list_filter = ('company',)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'parent', 'head', 'created_at')
    list_filter = ('company',)


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'level', 'created_at')
    list_filter = ('company',)


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


class BankCardInline(admin.TabularInline):
    model = BankCard
    extra = 0


@admin.register(BankCard)
class BankCardAdmin(admin.ModelAdmin):
    list_display = ('user', 'bank_name', 'bin_code', 'account_number', 'account_holder', 'is_primary', 'created_at')
    list_filter = ('is_primary', 'bank_name')
    search_fields = ('account_number', 'account_holder', 'user__username')


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = (ProfileInline, BankCardInline)
    add_form = CompanyUserCreationForm
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'company', 'usable_password', 'password1', 'password2'),
        }),
    )
    fieldsets = UserAdmin.fieldsets + (
        ('OAuth2', {'fields': ('application', 'company', 'role')}),
        ('Tổ chức', {'fields': ('department', 'position')}),
        ('Mật khẩu', {'fields': ('must_change_password',)}),
    )
    list_display = UserAdmin.list_display + ('application', 'company', 'role', 'department', 'position', 'must_change_password')
    list_filter = UserAdmin.list_filter + ('company', 'role', 'department', 'position', 'must_change_password')
