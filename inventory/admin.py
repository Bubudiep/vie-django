from django.contrib import admin

from .models import ProductRecipe, RecipeItem, StockCategory, StockItem, StockMovement


@admin.register(StockCategory)
class StockCategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'company', 'order')
    list_filter = ('company',)


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'category', 'company', 'unit', 'quantity_on_hand', 'reorder_level', 'is_active')
    list_filter = ('company', 'category', 'is_active')
    search_fields = ('name', 'sku')


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('id', 'item', 'movement_type', 'quantity', 'occurred_at', 'created_by')
    list_filter = ('company', 'movement_type')
    readonly_fields = ('occurred_date', 'created_at')

    def has_change_permission(self, request, obj=None):
        return False


class RecipeItemInline(admin.TabularInline):
    model = RecipeItem
    extra = 1


@admin.register(ProductRecipe)
class ProductRecipeAdmin(admin.ModelAdmin):
    inlines = (RecipeItemInline,)
    list_display = ('id', 'product', 'updated_at')
    search_fields = ('product__name',)
