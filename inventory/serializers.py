from decimal import Decimal

from rest_framework import serializers

from .models import ProductRecipe, RecipeItem, StockCategory, StockItem, StockMovement


class StockCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = StockCategory
        fields = ('id', 'name', 'order')
        read_only_fields = ('id',)


class StockItemSerializer(serializers.ModelSerializer):
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = StockItem
        fields = (
            'id', 'category', 'name', 'unit', 'sku', 'quantity_on_hand',
            'reorder_level', 'is_low_stock', 'is_active', 'created_at',
        )
        read_only_fields = ('id', 'quantity_on_hand', 'is_low_stock', 'created_at')


class StockMovementSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    unit = serializers.CharField(source='item.unit', read_only=True)

    class Meta:
        model = StockMovement
        fields = (
            'id', 'item', 'item_name', 'unit', 'movement_type', 'quantity',
            'unit_cost', 'reference', 'created_by', 'occurred_at', 'created_at',
        )
        read_only_fields = ('id', 'item_name', 'unit', 'created_by', 'created_at')


class StockMovementCreateSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal('0.001'))
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)
    reference = serializers.CharField(required=False, allow_blank=True, default='')
    occurred_at = serializers.DateTimeField(required=False, allow_null=True)


class RecipeItemSerializer(serializers.ModelSerializer):
    stock_item_name = serializers.CharField(source='stock_item.name', read_only=True)
    unit = serializers.CharField(source='stock_item.unit', read_only=True)

    class Meta:
        model = RecipeItem
        fields = ('id', 'stock_item', 'stock_item_name', 'unit', 'quantity')
        read_only_fields = ('id', 'stock_item_name', 'unit')


class RecipeItemInputSerializer(serializers.Serializer):
    stock_item_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal('0.001'))


class ProductRecipeSerializer(serializers.ModelSerializer):
    items = RecipeItemSerializer(many=True, read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = ProductRecipe
        fields = ('id', 'product', 'product_name', 'note', 'items', 'updated_at')
        read_only_fields = ('id', 'product_name', 'items', 'updated_at')


class ProductRecipeSetSerializer(serializers.Serializer):
    """Full replace of a recipe's ingredient list."""

    note = serializers.CharField(required=False, allow_blank=True, default='')
    items = RecipeItemInputSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError('Cần ít nhất 1 nguyên liệu.')
        return value


class RequiredMaterialSerializer(serializers.Serializer):
    stock_item = serializers.IntegerField(source='stock_item.id')
    stock_item_name = serializers.CharField(source='stock_item.name')
    unit = serializers.CharField(source='stock_item.unit')
    required_quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    on_hand = serializers.DecimalField(max_digits=14, decimal_places=3)
    shortage = serializers.DecimalField(max_digits=14, decimal_places=3)


class ProduceRequestSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal('0.001'))
    reference = serializers.CharField(required=False, allow_blank=True, default='')
