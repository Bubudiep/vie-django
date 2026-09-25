import logging

from accounts.permissions import MatchesCompanyHeader
from accounts.signals import broadcast_to_company, send_user_notification
from django.db import models
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Category, Customer, Floor, Order, Product, Table, TableBooking, TableSession
from .serializers import (
    CategorySerializer,
    CustomerSerializer,
    FloorSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    ProductSerializer,
    TableBookingSerializer,
    TableSerializer,
    TableSessionSerializer,
)
from .services import build_menu, close_table, confirm_booking, create_order, get_or_create_customer, open_table, session_bill

logger = logging.getLogger(__name__)


class CompanyScopedMixin:
    """Every view here is company-scoped: it only ever sees/creates rows for
    request.user.company_id, and requires the X-Company-Id header to match.
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def perform_create(self, serializer):
        serializer.save(company_id=self.request.user.company_id)


class CategoryListCreateView(CompanyScopedMixin, ListCreateAPIView):
    serializer_class = CategorySerializer

    def get_queryset(self):
        return Category.objects.filter(company_id=self.request.user.company_id)


class CategoryDetailView(CompanyScopedMixin, RetrieveUpdateDestroyAPIView):
    serializer_class = CategorySerializer

    def get_queryset(self):
        return Category.objects.filter(company_id=self.request.user.company_id)


class ProductListCreateView(CompanyScopedMixin, ListCreateAPIView):
    """?kind=goods|food|drink and/or ?category=<id> filter the catalog."""

    serializer_class = ProductSerializer

    def get_queryset(self):
        qs = Product.objects.filter(company_id=self.request.user.company_id).select_related('category')
        kind = self.request.query_params.get('kind')
        if kind:
            qs = qs.filter(kind=kind)
        category_id = self.request.query_params.get('category')
        if category_id:
            qs = qs.filter(category_id=category_id)
        return qs


class ProductDetailView(CompanyScopedMixin, RetrieveUpdateDestroyAPIView):
    serializer_class = ProductSerializer

    def get_queryset(self):
        return Product.objects.filter(company_id=self.request.user.company_id)


class MenuView(APIView):
    """Customer-ordering menu: active + show_in_menu products, grouped by
    category (uncategorized products come back under a trailing "Khác"
    bucket). Each product carries `in_stock` so the frontend can grey out
    items that are out of stock without hiding them from the menu.
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get(self, request, *args, **kwargs):
        return Response(build_menu(request.user.company))


class FloorListCreateView(CompanyScopedMixin, ListCreateAPIView):
    serializer_class = FloorSerializer

    def get_queryset(self):
        return Floor.objects.filter(company_id=self.request.user.company_id)


class FloorDetailView(CompanyScopedMixin, RetrieveUpdateDestroyAPIView):
    serializer_class = FloorSerializer

    def get_queryset(self):
        return Floor.objects.filter(company_id=self.request.user.company_id)


class TableListCreateView(CompanyScopedMixin, ListCreateAPIView):
    """List/create tables. ?floor=<id> filters to one floor. Each table carries
    its layout position (pos_x/pos_y/width/height) for a floor-plan view.
    """

    serializer_class = TableSerializer

    def get_queryset(self):
        qs = Table.objects.filter(company_id=self.request.user.company_id).select_related('floor')
        floor_id = self.request.query_params.get('floor')
        if floor_id:
            qs = qs.filter(floor_id=floor_id)
        return qs

    def perform_create(self, serializer):
        floor = serializer.validated_data['floor']
        if floor.company_id != self.request.user.company_id:
            raise PermissionDenied('Tầng không thuộc công ty của bạn.')
        serializer.save(company_id=self.request.user.company_id)


class TableDetailView(CompanyScopedMixin, RetrieveUpdateDestroyAPIView):
    """PATCH is also how the frontend persists a table's dragged position on the floor plan."""

    serializer_class = TableSerializer

    def get_queryset(self):
        return Table.objects.filter(company_id=self.request.user.company_id)


class TableOpenView(APIView):
    """Open a session on a table — marks it occupied and, for billiards/karaoke, starts the hourly clock.

    Optionally attach a member (`customer_id`, or `customer_phone` to
    look up/create one on the spot) so close_table can bill against their
    membership card later.

    Broadcasts to everyone in the company's realtime room so staff see a
    customer renting a table/room the moment it happens (no polling needed).
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, table_id, *args, **kwargs):
        table = get_object_or_404(Table, pk=table_id, company_id=request.user.company_id)
        guest_count = int(request.data.get('guest_count') or 1)

        customer = None
        if request.data.get('customer_id'):
            customer = get_object_or_404(Customer, pk=request.data['customer_id'], company_id=request.user.company_id)
        elif request.data.get('customer_phone'):
            customer = get_or_create_customer(request.user.company, request.data['customer_phone'], request.data.get('customer_name', ''))

        try:
            session = open_table(table, request.user, guest_count, customer=customer)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        logger.info('Table opened: table_id=%s session_id=%s by user_id=%s', table.pk, session.pk, request.user.pk)
        broadcast_to_company(
            request.user.company, 'table_opened',
            {'table_id': table.pk, 'table_name': table.name, 'floor_id': table.floor_id, 'session_id': session.pk},
            actor=request.user,
            comment=f'{table.name} vừa được mở bởi {request.user.username}.',
        )
        return Response(TableSessionSerializer(session).data, status=201)


class TableCloseView(APIView):
    """Close a table's current session — computes the final bill (rental + order
    items) and frees the table. Broadcasts the freed-up table to the company,
    and sends the final bill back to whoever opened it (the "thông tin chủ
    quán gửi lại" the customer is waiting on) as a private realtime notification.
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, table_id, *args, **kwargs):
        table = get_object_or_404(Table, pk=table_id, company_id=request.user.company_id)
        session = get_object_or_404(TableSession, table=table, status=TableSession.OPEN)
        try:
            session = close_table(session, request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        logger.info('Table closed: table_id=%s session_id=%s by user_id=%s', table.pk, session.pk, request.user.pk)

        broadcast_to_company(
            request.user.company, 'table_closed',
            {'table_id': table.pk, 'table_name': table.name, 'session_id': session.pk},
            actor=request.user,
            comment=f'{table.name} đã được đóng, bàn hiện đang trống.',
        )
        if session.opened_by_id:
            bill = {k: float(v) for k, v in session_bill(session).items()}
            send_user_notification(
                session.opened_by, 'table_closed',
                {'table_id': table.pk, 'table_name': table.name, 'session_id': session.pk, 'bill': bill},
                comment=f'{table.name} đã đóng. Tổng hóa đơn: {bill["grand_total"]:,.0f}đ.',
            )
        return Response(TableSessionSerializer(session).data)


class CustomerListCreateView(CompanyScopedMixin, ListCreateAPIView):
    """?q=<text> searches name/phone — the POS "type to find a customer" lookup."""

    serializer_class = CustomerSerializer

    def get_queryset(self):
        qs = Customer.objects.filter(company_id=self.request.user.company_id)
        q = self.request.query_params.get('q')
        if q:
            qs = qs.filter(models.Q(name__icontains=q) | models.Q(phone__icontains=q))
        return qs

    def perform_create(self, serializer):
        phone = serializer.validated_data.get('phone')
        if phone and Customer.objects.filter(company_id=self.request.user.company_id, phone=phone).exists():
            raise ValidationError({'phone': 'Số điện thoại này đã có khách hàng khác sử dụng.'})
        serializer.save(company_id=self.request.user.company_id)


class CustomerDetailView(CompanyScopedMixin, RetrieveUpdateDestroyAPIView):
    serializer_class = CustomerSerializer

    def get_queryset(self):
        return Customer.objects.filter(company_id=self.request.user.company_id)


class CustomerOrdersView(CompanyScopedMixin, ListAPIView):
    """A customer's own order history."""

    serializer_class = OrderSerializer

    def get_queryset(self):
        customer = get_object_or_404(Customer, pk=self.kwargs['customer_id'], company_id=self.request.user.company_id)
        return (
            Order.objects.filter(customer=customer)
            .select_related('created_by')
            .prefetch_related('items')
        )


class OrderListCreateView(CompanyScopedMixin, ListCreateAPIView):
    """GET: list orders (optionally ?session=<id>, ?customer=<id>). POST:
    place an order — takeaway if `session_id` is omitted, else tied to an
    open table session. A customer can be attached by `customer_id`, or by
    `customer_phone` (+ optional `customer_name`) to look up/create one on
    the fly — the usual POS flow of just typing a phone number.
    """

    def get_serializer_class(self):
        return OrderCreateSerializer if self.request.method == 'POST' else OrderSerializer

    def get_queryset(self):
        qs = (
            Order.objects.filter(company_id=self.request.user.company_id)
            .select_related('created_by', 'customer')
            .prefetch_related('items')
        )
        session_id = self.request.query_params.get('session')
        if session_id:
            qs = qs.filter(session_id=session_id)
        customer_id = self.request.query_params.get('customer')
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        session = None
        if data.get('session_id'):
            session = get_object_or_404(
                TableSession, pk=data['session_id'], table__company_id=request.user.company_id, status=TableSession.OPEN,
            )

        customer = None
        if data.get('customer_id'):
            customer = get_object_or_404(Customer, pk=data['customer_id'], company_id=request.user.company_id)
        elif data.get('customer_phone'):
            customer = get_or_create_customer(request.user.company, data['customer_phone'], data.get('customer_name', ''))

        product_ids = [item['product_id'] for item in data['items']]
        products_by_id = {
            p.pk: p for p in Product.objects.filter(pk__in=product_ids, company_id=request.user.company_id, is_active=True)
        }
        missing = set(product_ids) - set(products_by_id)
        if missing:
            return Response({'detail': f'Sản phẩm không tồn tại: {sorted(missing)}'}, status=400)

        items = [
            {'product': products_by_id[item['product_id']], 'quantity': item['quantity']}
            for item in data['items']
        ]
        order = create_order(request.user.company, session, request.user, items, data.get('note', ''), customer=customer)
        logger.info(
            'Order created: order_id=%s session_id=%s customer_id=%s by user_id=%s',
            order.pk, session.pk if session else None, customer.pk if customer else None, request.user.pk,
        )
        broadcast_to_company(
            request.user.company, 'order_created',
            {'order_id': order.pk, 'session_id': session.pk if session else None, 'item_count': len(items)},
            actor=request.user,
            comment=f'Đơn hàng #{order.pk} vừa được tạo bởi {request.user.username}.',
        )
        return Response(OrderSerializer(order).data, status=201)


class OrderDetailView(CompanyScopedMixin, RetrieveAPIView):
    serializer_class = OrderSerializer

    def get_queryset(self):
        return (
            Order.objects.filter(company_id=self.request.user.company_id)
            .select_related('created_by', 'customer')
            .prefetch_related('items')
        )


class OrderStatusView(APIView):
    """Update an order's status (e.g. mark served, cancel) and let the
    customer who placed it know in realtime — the "thông tin chủ quán gửi
    lại" for an order, as opposed to table_closed's for a table/room rental.
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, order_id, *args, **kwargs):
        order = get_object_or_404(Order, pk=order_id, company_id=request.user.company_id)
        status_value = request.data.get('status')
        if status_value not in dict(Order.STATUS_CHOICES):
            return Response({'detail': 'Trạng thái không hợp lệ.'}, status=400)
        order.status = status_value
        order.save(update_fields=['status'])
        if order.created_by_id:
            send_user_notification(
                order.created_by, 'order_status_changed',
                {'order_id': order.pk, 'status': order.status},
                comment=f'Đơn hàng #{order.pk} đã chuyển sang trạng thái "{order.get_status_display()}".',
            )
        if order.customer_id:
            from chat.utils import notify_customer
            notify_customer(order.customer_id, {
                'event': 'order_status_changed', 'order_id': order.pk, 'status': order.status,
            })
        return Response(OrderSerializer(order).data)


class StaffBookingListView(CompanyScopedMixin, ListAPIView):
    """Staff view of every member booking — ?status=pending etc. to filter."""

    serializer_class = TableBookingSerializer

    def get_queryset(self):
        qs = TableBooking.objects.filter(company_id=self.request.user.company_id).select_related('table', 'customer')
        status_value = self.request.query_params.get('status')
        if status_value:
            qs = qs.filter(status=status_value)
        return qs


class BookingConfirmView(APIView):
    """Staff confirms a member's booking request."""

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, pk, *args, **kwargs):
        booking = get_object_or_404(TableBooking, pk=pk, company_id=request.user.company_id)
        try:
            booking, session = confirm_booking(booking, request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)

        from chat.utils import notify_customer
        notify_customer(booking.customer_id, {
            'event': 'booking_confirmed', 'booking_id': booking.pk, 'table_name': booking.table.name,
            'start_time': booking.start_time.isoformat(), 'opened_now': session is not None,
        })
        if session:
            broadcast_to_company(
                request.user.company, 'table_opened',
                {'table_id': booking.table.pk, 'table_name': booking.table.name, 'floor_id': booking.table.floor_id, 'session_id': session.pk},
                actor=request.user,
                comment=f'{booking.table.name} được mở tự động do xác nhận đặt bàn của {booking.customer.name}.',
            )
        return Response(TableBookingSerializer(booking).data)


class StaffBookingCancelView(APIView):
    """Staff cancels a member's booking (e.g. table unavailable)."""

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, pk, *args, **kwargs):
        booking = get_object_or_404(TableBooking, pk=pk, company_id=request.user.company_id)
        if booking.status in (TableBooking.CANCELLED, TableBooking.COMPLETED):
            return Response({'detail': 'Đặt bàn này không thể hủy.'}, status=400)
        booking.status = TableBooking.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.save(update_fields=['status', 'cancelled_at'])
        from chat.utils import notify_customer
        notify_customer(booking.customer_id, {
            'event': 'booking_cancelled', 'booking_id': booking.pk, 'table_name': booking.table.name,
        })
        return Response(TableBookingSerializer(booking).data)
