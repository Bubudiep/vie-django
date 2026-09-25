from django.conf import settings
from django.db import models
from django.utils import timezone


class StockCategory(models.Model):
    """Groups warehouse items for later analysis (e.g. "Nguyên liệu tươi", "Gia vị", "Bao bì")."""

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='stock_categories')
    name = models.CharField(max_length=150)
    order = models.PositiveIntegerField('thứ tự', default=0)

    class Meta:
        ordering = ['order', 'name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_stockcategory_name_per_company'),
        ]

    def __str__(self):
        return self.name


class StockItem(models.Model):
    """A raw material / ingredient / supply tracked in the warehouse — distinct
    from store.Product, which is what gets sold. A StockItem is consumed by a
    ProductRecipe to produce sellable Products.
    """

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='stock_items')
    category = models.ForeignKey(
        StockCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_items',
    )
    name = models.CharField(max_length=255)
    unit = models.CharField('đơn vị tính', max_length=50, default='kg')
    sku = models.CharField('mã kho', max_length=100, blank=True)
    # Denormalized running balance — kept in sync by inventory.services.stock_in/
    # stock_out inside a transaction, so reads never have to sum the movement
    # ledger to know "how much is on hand right now".
    quantity_on_hand = models.DecimalField('tồn kho hiện tại', max_digits=14, decimal_places=3, default=0)
    reorder_level = models.DecimalField(
        'ngưỡng cảnh báo', max_digits=14, decimal_places=3, null=True, blank=True,
        help_text='Cảnh báo khi tồn kho xuống dưới mức này. Để trống nếu không cần cảnh báo.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'sku'], condition=~models.Q(sku=''), name='unique_stockitem_sku_per_company',
            ),
        ]
        indexes = [
            models.Index(fields=['company', 'category'], name='stockitem_company_category_idx'),
        ]

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return self.reorder_level is not None and self.quantity_on_hand <= self.reorder_level


class StockMovement(models.Model):
    """One warehouse transaction line — an inbound purchase/receipt, or an
    outbound consumption/waste. `occurred_date` is a plain DateField kept in
    sync with `occurred_at` purely so day/month/year statistics can filter on
    an indexed column instead of truncating a timestamp on every row.
    """

    IN = 'in'
    OUT = 'out'
    MOVEMENT_TYPE_CHOICES = [(IN, 'Nhập kho'), (OUT, 'Xuất kho')]

    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='stock_movements')
    item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name='movements')
    movement_type = models.CharField(max_length=3, choices=MOVEMENT_TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField('đơn giá', max_digits=14, decimal_places=2, null=True, blank=True)
    reference = models.CharField('ghi chú / tham chiếu', max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+',
    )
    occurred_at = models.DateTimeField(default=timezone.now)
    occurred_date = models.DateField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-occurred_at', '-pk']
        indexes = [
            # Every stats query filters by company (+ optionally item/type)
            # and a date range — these composite indexes keep that range scan
            # sargable instead of falling back to a full table scan as the
            # ledger grows.
            models.Index(fields=['company', 'occurred_date'], name='stockmove_company_date_idx'),
            models.Index(fields=['item', 'occurred_date'], name='stockmove_item_date_idx'),
            models.Index(fields=['company', 'movement_type', 'occurred_date'], name='stockmove_type_date_idx'),
        ]

    def save(self, *args, **kwargs):
        self.occurred_date = self.occurred_at.date()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.get_movement_type_display()} {self.quantity} {self.item.unit} - {self.item.name}'


class ProductRecipe(models.Model):
    """The BOM (bill of materials) for one sellable store.Product — which
    StockItems, and how much of each, are consumed to produce one unit of it.
    """

    product = models.OneToOneField('store.Product', on_delete=models.CASCADE, related_name='recipe')
    note = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Công thức: {self.product}'


class RecipeItem(models.Model):
    recipe = models.ForeignKey(ProductRecipe, on_delete=models.CASCADE, related_name='items')
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name='+')
    quantity = models.DecimalField('định lượng / 1 sản phẩm', max_digits=14, decimal_places=3)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['recipe', 'stock_item'], name='unique_recipe_item'),
        ]

    def __str__(self):
        return f'{self.quantity} {self.stock_item.unit} {self.stock_item.name}'
