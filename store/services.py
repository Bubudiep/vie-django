from decimal import ROUND_CEILING, Decimal

from django.db import transaction
from django.utils import timezone

from .models import Category, Customer, Order, OrderItem, Product, Table, TableBooking, TableSession


def build_menu(company):
    """Active + show_in_menu products for `company`, grouped by category
    (uncategorized products come back under a trailing "Khác" bucket).
    Shared by the staff-facing store.api.MenuView and the member-facing
    membership.api.MenuView — same menu, two audiences.
    """
    from .serializers import MenuCategorySerializer, ProductSerializer

    products = list(
        Product.objects.filter(company_id=company.pk, is_active=True, show_in_menu=True)
        .select_related('category')
        .order_by('name')
    )
    categories = list(Category.objects.filter(company_id=company.pk).order_by('order', 'name'))

    by_category = {}
    uncategorized = []
    for product in products:
        if product.category_id:
            by_category.setdefault(product.category_id, []).append(product)
        else:
            uncategorized.append(product)

    visible_categories = []
    for category in categories:
        category.menu_products = by_category.get(category.pk, [])
        if category.menu_products:
            visible_categories.append(category)

    data = MenuCategorySerializer(visible_categories, many=True).data
    if uncategorized:
        data.append({
            'id': None, 'name': 'Khác', 'order': None,
            'products': ProductSerializer(uncategorized, many=True).data,
        })
    return data


def get_or_create_customer(company, phone, name=''):
    """POS-style lookup: an existing customer by phone is reused (and its
    name refreshed if a new one was given), otherwise a new record is made."""
    phone = (phone or '').strip()
    if not phone:
        return Customer.objects.create(company=company, name=name or 'Khách lẻ')

    customer, created = Customer.objects.get_or_create(
        company=company, phone=phone, defaults={'name': name or phone},
    )
    if not created and name and customer.name != name:
        customer.name = name
        customer.save(update_fields=['name'])
    return customer


def open_table(table, user, guest_count=1, customer=None):
    """Start a new session on `table` — marks it occupied and, for hourly-rated
    tables (billiards/karaoke), starts the clock used to bill rental time.
    `customer` (optional) is the member sitting at the table, if staff
    attached one — lets close_table later bill against their membership card.
    """
    with transaction.atomic():
        table = Table.objects.select_for_update().get(pk=table.pk)
        if table.status == Table.OCCUPIED:
            raise ValueError('Bàn đang được sử dụng.')
        session = TableSession.objects.create(table=table, opened_by=user, guest_count=guest_count, customer=customer)
        table.status = Table.OCCUPIED
        table.save(update_fields=['status'])

    if customer:
        from membership.services import earn_points_for_visit
        earn_points_for_visit(customer)

    return session


def _elapsed_minutes(session):
    return Decimal(str((timezone.now() - session.opened_at).total_seconds())) / Decimal('60')


def _block_rental_amount(hourly_rate, minutes):
    """Block-time billing: any part of an hour is charged as a full hour
    (1 phút cũng tính đủ 1 block 1 tiếng) — the club's actual pricing model,
    as opposed to prorating by the minute.
    """
    if not hourly_rate or minutes <= 0:
        return Decimal('0')
    hours = (minutes / Decimal('60')).to_integral_value(rounding=ROUND_CEILING)
    return (hourly_rate * hours).quantize(Decimal('1'))


def _card_coverage_minutes(session, elapsed_minutes):
    """How many of `elapsed_minutes` a linked membership card could cover —
    read-only preview used by session_bill; close_table does the real spend.
    """
    if not (session.customer_id and session.table.hourly_rate):
        return Decimal('0')
    from membership.services import get_or_create_card

    card = get_or_create_card(session.customer)
    return min(card.remaining_minutes, elapsed_minutes) if card.remaining_minutes > 0 else Decimal('0')


def open_table_bill(session):
    """Live rental estimate for a still-open session: actual elapsed minutes
    are covered by the card first (a time wallet — no rounding, that would
    either shortchange or overcharge the member's own prepaid balance), then
    whatever's left over is billed in cash by the hour-block rule above.
    """
    elapsed_minutes = _elapsed_minutes(session)
    card_minutes = _card_coverage_minutes(session, elapsed_minutes)
    cash_minutes = max(elapsed_minutes - card_minutes, Decimal('0'))
    return _block_rental_amount(session.table.hourly_rate, cash_minutes), card_minutes


def close_table(session, user):
    """Close a session — computes the hourly rental fee (if any), covering as
    much of it as possible from the member's membership card (if the session
    has a customer with a card balance), and frees the table.
    """
    with transaction.atomic():
        # `of=('self',)` locks only tablesession's own row — plain
        # select_for_update() would try to lock the joined `customer` row too,
        # and Postgres rejects FOR UPDATE across an outer join (customer is nullable).
        session = TableSession.objects.select_for_update(of=('self',)).select_related('table', 'customer').get(pk=session.pk)
        if session.status == TableSession.CLOSED:
            raise ValueError('Phiên đã được đóng.')

        elapsed_minutes = _elapsed_minutes(session)
        card_minutes_used = Decimal('0')

        if session.customer_id and session.table.hourly_rate:
            from membership.services import consume_card_minutes, get_or_create_card

            card = get_or_create_card(session.customer)
            if card.remaining_minutes > 0:
                card_minutes_used = consume_card_minutes(
                    card, elapsed_minutes, session=session, note=f'Sử dụng {session.table.name}',
                )

        cash_minutes = max(elapsed_minutes - card_minutes_used, Decimal('0'))
        rental_amount = _block_rental_amount(session.table.hourly_rate, cash_minutes)

        session.rental_amount = rental_amount
        session.card_minutes_used = card_minutes_used
        session.closed_at = timezone.now()
        session.closed_by = user
        session.status = TableSession.CLOSED
        session.save(update_fields=['rental_amount', 'card_minutes_used', 'closed_at', 'closed_by', 'status'])

        table = session.table
        table.status = Table.AVAILABLE
        table.save(update_fields=['status'])

    if session.customer_id:
        from membership.services import earn_points_for_spend

        items_total = sum(
            (item.total_price for item in OrderItem.objects.filter(order__session=session).exclude(order__status=Order.CANCELLED)),
            Decimal('0'),
        )
        earn_points_for_spend(session.customer, rental_amount + items_total, session=session)

    return session


def switch_table(session, new_table, user=None):
    """Move an open session to a different (available) table — same tab,
    same opened_at/orders, billing continues off the new table's hourly_rate.
    A simplification: it doesn't try to split billing across two rates for
    the time spent at each table, which is fine while every table shares the
    same hourly_rate (true for this club today).
    """
    with transaction.atomic():
        session = TableSession.objects.select_for_update(of=('self',)).select_related('table').get(pk=session.pk)
        if session.status != TableSession.OPEN:
            raise ValueError('Phiên đã đóng.')
        new_table = Table.objects.select_for_update().get(pk=new_table.pk)
        if new_table.pk == session.table_id:
            raise ValueError('Bàn mới trùng với bàn hiện tại.')
        if new_table.status != Table.AVAILABLE:
            raise ValueError(f'{new_table.name} hiện không trống.')

        old_table = session.table
        old_table.status = Table.AVAILABLE
        old_table.save(update_fields=['status'])

        new_table.status = Table.OCCUPIED
        new_table.save(update_fields=['status'])

        session.table = new_table
        session.save(update_fields=['table'])
    return session, old_table, new_table


def confirm_booking(booking, user=None):
    """Staff confirms a pending booking. If the requested time window already
    covers right now (the common case for a QR "mở bàn ngay" request, or a
    walk-in staff confirms exactly on time), the table is opened immediately
    for that member instead of being left CONFIRMED for staff to open by hand
    later. Returns (booking, session_or_None).
    """
    if booking.status != TableBooking.PENDING:
        raise ValueError('Chỉ có thể xác nhận đặt bàn đang chờ.')

    booking.status = TableBooking.CONFIRMED
    booking.save(update_fields=['status'])

    session = None
    now = timezone.now()
    if booking.start_time <= now < booking.end_time and booking.table.status == Table.AVAILABLE:
        try:
            session = open_table(booking.table, user, customer=booking.customer)
        except ValueError:
            session = None
        else:
            booking.status = TableBooking.COMPLETED
            booking.save(update_fields=['status'])

    return booking, session


def table_reserved_now(table):
    """True if `table` has a pending/confirmed booking whose window covers
    this exact moment — used to block "mở bàn ngay" even when Table.status
    hasn't been flipped to occupied yet (staff hasn't opened it, but someone
    already has it reserved for right now).
    """
    now = timezone.now()
    return any(
        booking.start_time <= now < booking.end_time
        for booking in TableBooking.objects.filter(
            table=table, status__in=(TableBooking.PENDING, TableBooking.CONFIRMED),
        )
    )


def booking_conflicts(table, start_time, duration_minutes, exclude_pk=None):
    """True if [start_time, start_time+duration) overlaps an existing
    pending/confirmed booking on `table` — checked when a member books ahead.
    """
    from datetime import timedelta

    end_time = start_time + timedelta(minutes=duration_minutes)
    qs = TableBooking.objects.filter(table=table, status__in=(TableBooking.PENDING, TableBooking.CONFIRMED))
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return any(booking.start_time < end_time and booking.end_time > start_time for booking in qs)


def session_bill(session):
    """Rental time (if any) + every non-cancelled order placed under this
    session. For a still-open session, the rental portion is a live estimate
    (open_table_bill); for a closed one it's the amount actually charged.
    """
    items_total = sum(
        (item.total_price for item in OrderItem.objects.filter(order__session=session).exclude(order__status=Order.CANCELLED)),
        Decimal('0'),
    )
    if session.status == TableSession.OPEN:
        rental_amount, _card_minutes = open_table_bill(session)
    else:
        rental_amount = session.rental_amount
    return {
        'rental_amount': rental_amount,
        'items_total': items_total,
        'grand_total': rental_amount + items_total,
    }


def customer_stats(customer):
    """Order count + lifetime spend for one customer (non-cancelled orders only)."""
    from django.db.models import DecimalField, F, Sum

    orders = customer.orders.exclude(status=Order.CANCELLED)
    total_spent = OrderItem.objects.filter(order__in=orders).aggregate(
        total=Sum(F('unit_price') * F('quantity'), output_field=DecimalField(max_digits=14, decimal_places=2)),
    )['total'] or Decimal('0')
    return {'order_count': orders.count(), 'total_spent': total_spent}


def create_order(company, session, user, items, note='', customer=None):
    """`items`: list of {'product': Product instance, 'quantity': Decimal}."""
    with transaction.atomic():
        order = Order.objects.create(company=company, session=session, customer=customer, created_by=user, note=note)
        OrderItem.objects.bulk_create([
            OrderItem(
                order=order, product=item['product'], product_name=item['product'].name,
                unit_price=item['product'].price, quantity=item['quantity'],
            )
            for item in items
        ])
    return order
