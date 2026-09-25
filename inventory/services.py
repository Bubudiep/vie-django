from decimal import Decimal

from django.db import transaction
from django.db.models import Case, DecimalField, F, Sum, Value, When
from django.db.models.functions import TruncDay, TruncMonth, TruncYear
from django.utils import timezone

from store.models import Product

from .models import ProductRecipe, StockItem, StockMovement


def _record_movement(item, movement_type, quantity, user, unit_cost, reference, occurred_at):
    quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise ValueError('Số lượng phải lớn hơn 0.')
    with transaction.atomic():
        item = StockItem.objects.select_for_update().get(pk=item.pk)
        if movement_type == StockMovement.OUT and item.quantity_on_hand < quantity:
            raise ValueError(f'Không đủ tồn kho: còn {item.quantity_on_hand} {item.unit}.')
        delta = quantity if movement_type == StockMovement.IN else -quantity
        item.quantity_on_hand = item.quantity_on_hand + delta
        item.save(update_fields=['quantity_on_hand'])
        movement = StockMovement.objects.create(
            company_id=item.company_id, item=item, movement_type=movement_type, quantity=quantity,
            unit_cost=unit_cost, reference=reference, created_by=user, occurred_at=occurred_at or timezone.now(),
        )
    return movement


def stock_in(item, quantity, user, unit_cost=None, reference='', occurred_at=None):
    return _record_movement(item, StockMovement.IN, quantity, user, unit_cost, reference, occurred_at)


def stock_out(item, quantity, user, reference='', occurred_at=None):
    return _record_movement(item, StockMovement.OUT, quantity, user, None, reference, occurred_at)


def required_materials(product, quantity):
    """For `quantity` units of `product`, how much of each recipe ingredient
    is needed, how much is on hand, and the shortfall still to be purchased —
    the "món này cần nhập gì" calculator.
    """
    try:
        recipe = product.recipe
    except ProductRecipe.DoesNotExist:
        raise ValueError('Sản phẩm chưa có công thức.')

    quantity = Decimal(str(quantity))
    result = []
    for line in recipe.items.select_related('stock_item'):
        required = line.quantity * quantity
        on_hand = line.stock_item.quantity_on_hand
        shortage = max(required - on_hand, Decimal('0'))
        result.append({
            'stock_item': line.stock_item,
            'required_quantity': required,
            'on_hand': on_hand,
            'shortage': shortage,
        })
    return result


def produce(product, quantity, user, reference=''):
    """Consume a product's recipe to make `quantity` units — deducts every
    ingredient from the warehouse and, if the product itself tracks stock,
    credits the produced amount to it.
    """
    quantity = Decimal(str(quantity))
    materials = required_materials(product, quantity)
    with transaction.atomic():
        for line in materials:
            stock_out(line['stock_item'], line['required_quantity'], user, reference=reference or f'Sản xuất {product.name}')
        if product.track_stock:
            Product.objects.filter(pk=product.pk).update(stock_quantity=F('stock_quantity') + quantity)
    return materials


TRUNC_FUNCS = {'day': TruncDay, 'month': TruncMonth, 'year': TruncYear}


def movement_stats(company_id, group_by='day', date_from=None, date_to=None, item_id=None, category_id=None):
    """In/out totals grouped by day/month/year — filters on `occurred_date`
    only, so it stays index-friendly (see StockMovement.Meta.indexes).
    """
    qs = StockMovement.objects.filter(company_id=company_id)
    if date_from:
        qs = qs.filter(occurred_date__gte=date_from)
    if date_to:
        qs = qs.filter(occurred_date__lte=date_to)
    if item_id:
        qs = qs.filter(item_id=item_id)
    if category_id:
        qs = qs.filter(item__category_id=category_id)

    trunc = TRUNC_FUNCS.get(group_by, TruncDay)
    amount_field = DecimalField(max_digits=14, decimal_places=3)
    return list(
        qs.annotate(period=trunc('occurred_date'))
        .values('period')
        .annotate(
            in_quantity=Sum(
                Case(When(movement_type=StockMovement.IN, then='quantity'), default=Value(0), output_field=amount_field),
            ),
            out_quantity=Sum(
                Case(When(movement_type=StockMovement.OUT, then='quantity'), default=Value(0), output_field=amount_field),
            ),
        )
        .order_by('period')
    )
