from decimal import Decimal

from rest_framework import serializers

from .models import Category, Customer, Floor, Order, OrderItem, Product, Table, TableBooking, TableSession


class CustomerSerializer(serializers.ModelSerializer):
    order_count = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = ('id', 'name', 'phone', 'email', 'address', 'note', 'order_count', 'total_spent', 'created_at')
        read_only_fields = ('id', 'order_count', 'total_spent', 'created_at')

    def get_order_count(self, obj):
        return obj.orders.exclude(status=Order.CANCELLED).count()

    def get_total_spent(self, obj):
        from .services import customer_stats
        return customer_stats(obj)['total_spent']


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ('id', 'name', 'order')
        read_only_fields = ('id',)


class ProductSerializer(serializers.ModelSerializer):
    in_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = (
            'id', 'category', 'kind', 'name', 'unit', 'price', 'sku', 'image',
            'track_stock', 'stock_quantity', 'is_out_of_stock', 'in_stock',
            'show_in_menu', 'is_active', 'created_at',
        )
        read_only_fields = ('id', 'in_stock', 'created_at')


class MenuCategorySerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ('id', 'name', 'order', 'products')
        read_only_fields = fields

    def get_products(self, obj):
        return ProductSerializer(obj.menu_products, many=True).data


class FloorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Floor
        fields = ('id', 'name', 'order')
        read_only_fields = ('id',)


class TableSerializer(serializers.ModelSerializer):
    current_session_id = serializers.SerializerMethodField()

    class Meta:
        model = Table
        fields = (
            'id', 'floor', 'name', 'table_type', 'capacity', 'hourly_rate',
            'pos_x', 'pos_y', 'width', 'height', 'status', 'is_active', 'current_session_id', 'camera_url',
        )
        read_only_fields = ('id', 'status', 'current_session_id')

    def get_current_session_id(self, obj):
        session = obj.sessions.filter(status=TableSession.OPEN).first()
        return session.pk if session else None


class TableSessionSerializer(serializers.ModelSerializer):
    bill = serializers.SerializerMethodField()

    class Meta:
        model = TableSession
        fields = (
            'id', 'table', 'opened_by', 'closed_by', 'customer', 'guest_count', 'status',
            'opened_at', 'closed_at', 'rental_amount', 'card_minutes_used', 'bill',
        )
        read_only_fields = fields

    def get_bill(self, obj):
        from .services import session_bill
        return session_bill(obj)


class OrderItemSerializer(serializers.ModelSerializer):
    total_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ('id', 'product', 'product_name', 'unit_price', 'quantity', 'total_price')
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True, default=None)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True, default=None)
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Order
        fields = (
            'id', 'session', 'customer', 'customer_name', 'customer_phone', 'created_by', 'status', 'note',
            'total_amount', 'created_at', 'items',
        )
        read_only_fields = fields


class TableBookingSerializer(serializers.ModelSerializer):
    table_name = serializers.CharField(source='table.name', read_only=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True)
    end_time = serializers.DateTimeField(read_only=True)

    class Meta:
        model = TableBooking
        fields = (
            'id', 'table', 'table_name', 'customer', 'customer_name', 'customer_phone',
            'start_time', 'duration_minutes', 'end_time', 'note', 'status', 'created_at', 'cancelled_at',
        )
        read_only_fields = ('id', 'customer', 'status', 'created_at', 'cancelled_at', 'end_time')


class OrderItemInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), default=Decimal('1'))


class OrderCreateSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=False, allow_null=True)
    customer_id = serializers.IntegerField(required=False, allow_null=True)
    # POS-style shortcut: give a phone (+ optionally a name) instead of an
    # id, and the matching/newly-created Customer gets attached automatically.
    customer_phone = serializers.CharField(required=False, allow_blank=True)
    customer_name = serializers.CharField(required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True, default='')
    items = OrderItemInputSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError('Cần ít nhất 1 sản phẩm.')
        return value
