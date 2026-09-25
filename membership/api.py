import logging

from accounts.models import Company
from accounts.signals import broadcast_to_company
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from store.models import Floor, Table, TableBooking, TableSession
from store.serializers import (
    CustomerSerializer,
    FloorSerializer,
    TableBookingSerializer,
    TableSerializer,
    TableSessionSerializer,
)

from .authentication import CustomerTokenAuthentication
from .models import CardTransaction, CustomerVoucher, Event, MembershipPlan, PointsRedemptionOption, PointsTransaction
from .permissions import IsCustomerAuthenticated
from .serializers import (
    CardTransactionSerializer,
    CustomerVoucherSerializer,
    EventSerializer,
    MembershipCardSerializer,
    MembershipPlanSerializer,
    PointsAccountSerializer,
    PointsRedemptionOptionSerializer,
    PointsTransactionSerializer,
)
from .services import customer_login, get_or_create_card, get_or_create_points_account

logger = logging.getLogger(__name__)


class CustomerScopedMixin:
    """Every view here authenticates as a store.Customer (member) via their
    CustomerToken — the member-app equivalent of store.api.CompanyScopedMixin.
    """

    authentication_classes = (CustomerTokenAuthentication,)
    permission_classes = (IsCustomerAuthenticated,)

    @property
    def customer(self):
        return self.request.user


class CustomerLoginView(APIView):
    """POST {company_id, zalo_access_token, phone_token, name?} -> {token, customer, card, company}.

    `zalo_access_token` (from the frontend's getAccessToken()) and
    `phone_token` (from getPhoneNumber()) are exchanged server-side for the
    member's real phone number via resolve_zalo_phone — this is the actual
    verified login path.

    Dev-only fallback: while DEBUG=True and ZALO_APP_SECRET isn't configured
    yet, a raw `phone` in the request is accepted directly instead, so local
    testing (zmp start's browser preview, where the Zalo SDK calls above
    aren't available) still works. This path is refused once either DEBUG is
    off or the secret is set — don't rely on it past local development.
    """

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request, *args, **kwargs):
        company_id = request.data.get('company_id')
        name = (request.data.get('name') or '').strip()
        if not company_id:
            raise ValidationError({'detail': 'Cần company_id.'})
        company = get_object_or_404(Company, pk=company_id)

        zalo_access_token = request.data.get('zalo_access_token')
        phone_token = request.data.get('phone_token')
        raw_phone = (request.data.get('phone') or '').strip()

        if zalo_access_token and phone_token:
            from .services import resolve_zalo_phone
            try:
                phone = resolve_zalo_phone(zalo_access_token, phone_token)
            except ValueError as exc:
                raise ValidationError({'detail': str(exc)})
        elif settings.DEBUG and not settings.ZALO_APP_SECRET and raw_phone:
            phone = raw_phone
        else:
            raise ValidationError({'detail': 'Cần zalo_access_token và phone_token.'})

        customer, token = customer_login(company, phone, name)
        card = get_or_create_card(customer)
        logger.info('Customer login: customer_id=%s company_id=%s', customer.pk, company.pk)
        return Response({
            'token': token.key,
            'customer': CustomerSerializer(customer).data,
            'card': MembershipCardSerializer(card).data,
            'company': {'id': company.pk, 'name': company.name},
        })


class MeView(CustomerScopedMixin, APIView):
    def get(self, request, *args, **kwargs):
        card = get_or_create_card(self.customer)
        return Response({
            'customer': CustomerSerializer(self.customer).data,
            'card': MembershipCardSerializer(card).data,
            'company': {'id': self.customer.company_id, 'name': self.customer.company.name},
        })


class PlanListView(CustomerScopedMixin, ListAPIView):
    serializer_class = MembershipPlanSerializer

    def get_queryset(self):
        return MembershipPlan.objects.filter(company_id=self.customer.company_id, is_active=True)


class CardTransactionListView(CustomerScopedMixin, ListAPIView):
    serializer_class = CardTransactionSerializer

    def get_queryset(self):
        card = get_or_create_card(self.customer)
        return CardTransaction.objects.filter(card=card)


class PointsView(CustomerScopedMixin, APIView):
    """Balance for the "Điểm thưởng" tab — history is its own endpoint below."""

    def get(self, request, *args, **kwargs):
        account = get_or_create_points_account(self.customer)
        return Response(PointsAccountSerializer(account).data)


class PointsTransactionListView(CustomerScopedMixin, ListAPIView):
    serializer_class = PointsTransactionSerializer

    def get_queryset(self):
        account = get_or_create_points_account(self.customer)
        return PointsTransaction.objects.filter(account=account)


class PointsRedemptionOptionListView(CustomerScopedMixin, ListAPIView):
    serializer_class = PointsRedemptionOptionSerializer

    def get_queryset(self):
        return PointsRedemptionOption.objects.filter(company_id=self.customer.company_id, is_active=True)


class PointsRedeemView(CustomerScopedMixin, APIView):
    """The "Quy đổi" tab's action: spend points for playing time on the
    member's MembershipCard (see membership.services.redeem_points).
    """

    def post(self, request, *args, **kwargs):
        from .services import redeem_points

        option = get_object_or_404(
            PointsRedemptionOption, pk=request.data.get('option'), company_id=self.customer.company_id, is_active=True,
        )
        account = get_or_create_points_account(self.customer)
        try:
            account = redeem_points(account, option)
        except ValueError as exc:
            raise ValidationError({'detail': str(exc)})
        logger.info('Points redeemed: customer_id=%s option_id=%s', self.customer.pk, option.pk)
        return Response(PointsAccountSerializer(account).data)


class CustomerVoucherListView(CustomerScopedMixin, ListAPIView):
    serializer_class = CustomerVoucherSerializer

    def get_queryset(self):
        return CustomerVoucher.objects.filter(customer=self.customer).select_related('voucher')


class CustomerVoucherUseView(CustomerScopedMixin, APIView):
    """Member marks a voucher as about to be used at checkout — staff still
    has to actually honor the discount when collecting payment in person
    (no POS integration), same pattern as RequestPaymentView.
    """

    def post(self, request, pk, *args, **kwargs):
        customer_voucher = get_object_or_404(CustomerVoucher, pk=pk, customer=self.customer)
        if not customer_voucher.is_usable:
            raise ValidationError({'detail': 'Voucher này không còn sử dụng được.'})

        customer_voucher.status = CustomerVoucher.USED
        customer_voucher.used_at = timezone.now()
        customer_voucher.save(update_fields=['status', 'used_at'])

        broadcast_to_company(
            self.customer.company, 'voucher_used',
            {'customer_voucher_id': customer_voucher.pk, 'voucher_title': customer_voucher.voucher.title},
            actor=None,
            comment=f'{self.customer.name} sử dụng voucher "{customer_voucher.voucher.title}".',
        )
        logger.info('Voucher used: customer_voucher_id=%s customer_id=%s', customer_voucher.pk, self.customer.pk)
        return Response(CustomerVoucherSerializer(customer_voucher).data)


class MenuView(CustomerScopedMixin, APIView):
    """Read-only drinks/snacks menu for the "Đồ uống" tab — members browse,
    staff still takes the actual order (no self-order flow here yet).
    """

    def get(self, request, *args, **kwargs):
        from store.services import build_menu

        return Response(build_menu(self.customer.company))


class EventListView(CustomerScopedMixin, ListAPIView):
    serializer_class = EventSerializer

    def get_queryset(self):
        return Event.objects.filter(company_id=self.customer.company_id, is_active=True)


class FloorListView(CustomerScopedMixin, ListAPIView):
    serializer_class = FloorSerializer

    def get_queryset(self):
        return Floor.objects.filter(company_id=self.customer.company_id)


class TableListView(CustomerScopedMixin, ListAPIView):
    """Read-only floor-plan/status view for members — ?floor=<id> to filter."""

    serializer_class = TableSerializer

    def get_queryset(self):
        qs = Table.objects.filter(company_id=self.customer.company_id, is_active=True).select_related('floor')
        floor_id = self.request.query_params.get('floor')
        if floor_id:
            qs = qs.filter(floor_id=floor_id)
        return qs


class TableDetailView(CustomerScopedMixin, RetrieveAPIView):
    """Single table lookup — what the QR-scan landing page fetches (the QR
    on each physical table just encodes this table's id).
    """

    serializer_class = TableSerializer

    def get_queryset(self):
        return Table.objects.filter(company_id=self.customer.company_id, is_active=True)


class RequestTableUseView(CustomerScopedMixin, APIView):
    """The QR-code flow: member scans the code stuck on a physical table,
    lands on a one-tap confirmation screen, and this creates an immediate
    request (a TableBooking with start_time=now) — reusing the exact same
    staff confirm/cancel path as an advance booking (BookingConfirmView /
    the Django admin actions) rather than a separate mechanism. Staff still
    has to actually open the table (TableOpenView, POS-side), same as today.
    """

    def post(self, request, table_id, *args, **kwargs):
        from store.services import table_reserved_now

        table = get_object_or_404(Table, pk=table_id, company_id=self.customer.company_id, is_active=True)
        if table.status != Table.AVAILABLE:
            raise ValidationError({'detail': f'{table.name} hiện không trống ({table.get_status_display()}).'})
        if table_reserved_now(table):
            raise ValidationError({'detail': f'{table.name} đã có người đặt trước cho khung giờ này.'})

        already_pending = TableBooking.objects.filter(
            table=table, customer=self.customer, status__in=(TableBooking.PENDING, TableBooking.CONFIRMED),
        ).exists()
        if already_pending:
            raise ValidationError({'detail': f'Bạn đã gửi yêu cầu {table.name} rồi, vui lòng chờ nhân viên xác nhận.'})

        booking = TableBooking.objects.create(
            company=self.customer.company, table=table, customer=self.customer,
            start_time=timezone.now(), duration_minutes=60, note='Yêu cầu qua quét mã QR tại bàn',
        )
        broadcast_to_company(
            self.customer.company, 'booking_created',
            {'booking_id': booking.pk, 'table_id': table.pk, 'table_name': table.name, 'start_time': booking.start_time.isoformat(), 'via_qr': True},
            actor=None,
            comment=f'{self.customer.name} yêu cầu sử dụng {table.name} ngay (quét mã QR).',
        )
        logger.info('Table use requested via QR: booking_id=%s customer_id=%s table_id=%s', booking.pk, self.customer.pk, table.pk)
        return Response(TableBookingSerializer(booking).data, status=201)


class MySessionView(CustomerScopedMixin, APIView):
    """The member's current open table session (if any), with its orders/
    items and running bill — the "trạng thái bàn của tôi + món đã gọi" screen.
    """

    def get(self, request, *args, **kwargs):
        session = (
            TableSession.objects.filter(customer=self.customer, status=TableSession.OPEN)
            .select_related('table')
            .first()
        )
        if not session:
            return Response({'session': None})

        from store.serializers import OrderSerializer
        from store.services import session_bill

        orders = session.orders.select_related('created_by').prefetch_related('items')
        return Response({
            'session': TableSessionSerializer(session).data,
            'orders': OrderSerializer(orders, many=True).data,
            'bill': {k: v for k, v in session_bill(session).items()},
        })


class SwitchTableView(CustomerScopedMixin, APIView):
    """"Đổi bàn": move the member's own open session to a different available
    table — same tab, same elapsed time, orders carry over.
    """

    def post(self, request, session_id, *args, **kwargs):
        from store.services import switch_table

        session = get_object_or_404(TableSession, pk=session_id, customer=self.customer, status=TableSession.OPEN)
        new_table = get_object_or_404(Table, pk=request.data.get('table'), company_id=self.customer.company_id, is_active=True)

        try:
            session, old_table, new_table = switch_table(session, new_table)
        except ValueError as exc:
            raise ValidationError({'detail': str(exc)})

        broadcast_to_company(
            self.customer.company, 'table_closed',
            {'table_id': old_table.pk, 'table_name': old_table.name, 'session_id': session.pk},
            actor=None, comment=f'{old_table.name} vừa được trả lại (đổi bàn).',
        )
        broadcast_to_company(
            self.customer.company, 'table_opened',
            {'table_id': new_table.pk, 'table_name': new_table.name, 'floor_id': new_table.floor_id, 'session_id': session.pk},
            actor=None, comment=f'{self.customer.name} đã chuyển sang {new_table.name}.',
        )
        logger.info(
            'Table switched: session_id=%s customer_id=%s old_table_id=%s new_table_id=%s',
            session.pk, self.customer.pk, old_table.pk, new_table.pk,
        )
        return Response(TableSessionSerializer(session).data)


class RequestPaymentView(CustomerScopedMixin, APIView):
    """The member's "Thanh toán" button: no online gateway wired up yet, so
    this just computes the current bill and pings staff in realtime to come
    collect payment in person.
    """

    def post(self, request, session_id, *args, **kwargs):
        from store.services import session_bill

        session = get_object_or_404(
            TableSession, pk=session_id, customer=self.customer, status=TableSession.OPEN,
        )
        bill = {k: float(v) for k, v in session_bill(session).items()}
        broadcast_to_company(
            self.customer.company, 'payment_requested',
            {'table_id': session.table_id, 'table_name': session.table.name, 'session_id': session.pk, 'bill': bill},
            actor=None,
            comment=f'{self.customer.name} yêu cầu thanh toán bàn {session.table.name}.',
        )
        logger.info('Payment requested: session_id=%s customer_id=%s', session.pk, self.customer.pk)
        return Response({'bill': bill})


class PaymentQrView(CustomerScopedMixin, APIView):
    """The member's "QR Thanh toán" button: a VietQR (img.vietqr.io) transfer
    QR pre-filled with the club's bank account + the session's current bill,
    so the member can pay by scanning with any banking app — no payment
    gateway integration needed. Requires VIETQR_* to be set in settings;
    until then this reports back that it isn't configured yet.
    """

    def get(self, request, session_id, *args, **kwargs):
        from urllib.parse import quote

        from store.services import session_bill

        session = get_object_or_404(
            TableSession, pk=session_id, customer=self.customer, status=TableSession.OPEN,
        )
        if not (settings.VIETQR_BANK_ID and settings.VIETQR_ACCOUNT_NO):
            raise ValidationError({'detail': 'Quán chưa cấu hình thanh toán QR.'})

        bill = session_bill(session)
        amount = int(bill['grand_total'])
        note = quote(f'Thanh toan {session.table.name}'[:25])
        qr_image_url = (
            f'https://img.vietqr.io/image/{settings.VIETQR_BANK_ID}-{settings.VIETQR_ACCOUNT_NO}-compact2.png'
            f'?amount={amount}&addInfo={note}'
        )
        if settings.VIETQR_ACCOUNT_NAME:
            qr_image_url += f'&accountName={quote(settings.VIETQR_ACCOUNT_NAME)}'

        return Response({
            'qr_image_url': qr_image_url,
            'bank_id': settings.VIETQR_BANK_ID,
            'account_no': settings.VIETQR_ACCOUNT_NO,
            'account_name': settings.VIETQR_ACCOUNT_NAME,
            'amount': amount,
        })


class BookingHistoryPagination(PageNumberPagination):
    """Newest-first, 5 per page — the member's "Đặt bàn của tôi" list can
    grow unbounded over time, unlike every other list here (tables/menu/
    events), which stay small and don't paginate.
    """

    page_size = 5
    page_query_param = 'page'


class BookingListCreateView(CustomerScopedMixin, ListCreateAPIView):
    serializer_class = TableBookingSerializer
    pagination_class = BookingHistoryPagination

    def get_queryset(self):
        return TableBooking.objects.filter(customer=self.customer).select_related('table').order_by('-id')

    def create(self, request, *args, **kwargs):
        from store.services import booking_conflicts

        table = get_object_or_404(Table, pk=request.data.get('table'), company_id=self.customer.company_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        start_time = serializer.validated_data['start_time']
        duration_minutes = serializer.validated_data.get('duration_minutes', 60)
        if booking_conflicts(table, start_time, duration_minutes):
            raise ValidationError({'detail': f'{table.name} đã có người đặt vào khung giờ này, vui lòng chọn giờ khác.'})

        booking = serializer.save(company=self.customer.company, table=table, customer=self.customer)
        broadcast_to_company(
            self.customer.company, 'booking_created',
            {'booking_id': booking.pk, 'table_id': table.pk, 'table_name': table.name, 'start_time': booking.start_time.isoformat()},
            actor=None,
            comment=f'{self.customer.name} vừa đặt {table.name} lúc {booking.start_time:%H:%M %d/%m}.',
        )
        logger.info('Booking created: booking_id=%s customer_id=%s table_id=%s', booking.pk, self.customer.pk, table.pk)
        return Response(TableBookingSerializer(booking).data, status=201)


class BookingCancelView(CustomerScopedMixin, APIView):
    def post(self, request, pk, *args, **kwargs):
        from django.utils import timezone

        booking = get_object_or_404(TableBooking, pk=pk, customer=self.customer)
        if booking.status in (TableBooking.CANCELLED, TableBooking.COMPLETED):
            raise ValidationError({'detail': 'Đặt bàn này không thể hủy.'})
        booking.status = TableBooking.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.save(update_fields=['status', 'cancelled_at'])
        logger.info('Booking cancelled by customer: booking_id=%s customer_id=%s', booking.pk, self.customer.pk)
        return Response(TableBookingSerializer(booking).data)
