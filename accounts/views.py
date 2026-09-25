import logging

from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.generics import CreateAPIView, ListAPIView, ListCreateAPIView, RetrieveAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import BankCard, Department, Notification, NotificationRead, Position, Role, User
from .permissions import IsCompanyAdminOrReadOnly, MatchesCompanyHeader
from .serializers import (
    BankCardSerializer,
    ChangePasswordSerializer,
    CompanySerializer,
    ContactSerializer,
    DepartmentSerializer,
    FirstChangePasswordSerializer,
    NotificationSerializer,
    PositionSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    UserAssignmentSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)

class RegisterView(CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = (AllowAny,)
    authentication_classes = ()

    def perform_create(self, serializer):
        user = serializer.save()
        logger.info('User registered: user_id=%s username=%r company_id=%r', user.pk, user.username, user.company_id)

class MeView(RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get_object(self):
        return self.request.user

class ProfileUpdateView(APIView):
    """Updates the current user's own "thông tin cá nhân": họ tên, tên hiển
    thị, link facebook, ghi chú cá nhân (bio), avatar, ảnh bìa (cover). Send
    as multipart/form-data when including an avatar and/or cover file."""

    permission_classes = (IsAuthenticated,)

    def patch(self, request, *args, **kwargs):
        serializer = ProfileUpdateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        logger.info('Profile updated: user_id=%s fields=%s', user.pk, list(serializer.validated_data.keys()))
        return Response(UserSerializer(user, context={'request': request}).data)


class BankCardListCreateView(ListCreateAPIView):
    """The current user's own bank cards — not company-scoped, a card
    belongs to a person, not the shop."""

    serializer_class = BankCardSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return BankCard.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        bin_code = serializer.validated_data.get('bin_code')
        account_number = serializer.validated_data.get('account_number')
        if BankCard.objects.filter(user=self.request.user, bin_code=bin_code, account_number=account_number).exists():
            raise ValidationError('Thẻ ngân hàng này đã tồn tại.')

        card = serializer.save(user=self.request.user)
        is_first_card = BankCard.objects.filter(user=self.request.user).count() == 1
        if is_first_card or self.request.data.get('is_primary'):
            from .services import set_primary_bank_card
            set_primary_bank_card(self.request.user, card)
        logger.info('Bank card added: user_id=%s card_id=%s bin_code=%r', self.request.user.pk, card.pk, card.bin_code)


class BankCardDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = BankCardSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return BankCard.objects.filter(user=self.request.user)


class BankCardSetPrimaryView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        card = get_object_or_404(BankCard, pk=kwargs['pk'], user=request.user)
        from .services import set_primary_bank_card
        set_primary_bank_card(request.user, card)
        logger.info('Bank card set primary: user_id=%s card_id=%s', request.user.pk, card.pk)
        return Response(BankCardSerializer(card).data)


class DepartmentListCreateView(ListCreateAPIView):
    serializer_class = DepartmentSerializer
    permission_classes = (IsAuthenticated, MatchesCompanyHeader, IsCompanyAdminOrReadOnly)

    def get_queryset(self):
        return Department.objects.filter(company_id=self.request.user.company_id).select_related('head')

    def perform_create(self, serializer):
        department = serializer.save(company=self.request.user.company)
        logger.info('Department created: company_id=%s department_id=%s name=%r', self.request.user.company_id, department.pk, department.name)


class DepartmentDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = DepartmentSerializer
    permission_classes = (IsAuthenticated, MatchesCompanyHeader, IsCompanyAdminOrReadOnly)

    def get_queryset(self):
        return Department.objects.filter(company_id=self.request.user.company_id).select_related('head')


class PositionListCreateView(ListCreateAPIView):
    serializer_class = PositionSerializer
    permission_classes = (IsAuthenticated, MatchesCompanyHeader, IsCompanyAdminOrReadOnly)

    def get_queryset(self):
        return Position.objects.filter(company_id=self.request.user.company_id)

    def perform_create(self, serializer):
        position = serializer.save(company=self.request.user.company)
        logger.info('Position created: company_id=%s position_id=%s name=%r', self.request.user.company_id, position.pk, position.name)


class PositionDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = PositionSerializer
    permission_classes = (IsAuthenticated, MatchesCompanyHeader, IsCompanyAdminOrReadOnly)

    def get_queryset(self):
        return Position.objects.filter(company_id=self.request.user.company_id)


class UserAssignmentView(APIView):
    """Admin-only: assign (or clear) a company member's department and/or
    position — the write side of the "chọn người cho phòng ban/chức vụ"
    directory feature."""

    permission_classes = (IsAuthenticated, MatchesCompanyHeader, IsCompanyAdminOrReadOnly)

    def patch(self, request, user_id, *args, **kwargs):
        target = get_object_or_404(User, pk=user_id, company_id=request.user.company_id)
        serializer = UserAssignmentSerializer(
            data=request.data, context={'request': request, 'target': target},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info(
            'User assignment changed: user_id=%s department_id=%s position_id=%s by admin_id=%s',
            target.pk, target.department_id, target.position_id, request.user.pk,
        )
        return Response(ContactSerializer(target, context={'request': request}).data)


class OrgChartView(APIView):
    """Nested department tree (with head + members) for the company's org chart."""

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get(self, request, *args, **kwargs):
        from .services import build_org_chart
        return Response(build_org_chart(request.user.company))


class CompanyView(RetrieveAPIView):
    """Current user's own company info."""

    serializer_class = CompanySerializer
    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get_object(self):
        return self.request.user.company

class ContactListView(ListAPIView):
    """Every active employee (non-system) of the current user's company."""

    serializer_class = ContactSerializer
    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get_queryset(self):
        return (
            User.objects.filter(company_id=self.request.user.company_id, is_active=True)
            .exclude(role__name=Role.SYSTEM)
            .select_related('role', 'profile')
            .order_by('username')
        )

class ChatSummaryView(ListAPIView):
    """Every chat room the current user can see, with its last message and
    unread count — a one-call overview for a chat home screen.
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def get_serializer_class(self):
        from chat.serializers import RoomSerializer
        return RoomSerializer

    def get_queryset(self):
        from chat.models import ChatRoom
        return (
            ChatRoom.objects.for_user(self.request.user)
            .select_related('company')
            .annotate_pinned(self.request.user)
            .order_by('-is_pinned_by_me', '-last_message_at', '-created_at')
        )

class ChangePasswordView(APIView):
    """Forced password change for the ``must_change_password`` flow after an
    admin-provisioned first login — no old password required since a
    successful login already proved identity.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        serializer = FirstChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info('First password change: user_id=%s', request.user.pk)
        return Response({'detail': 'Đổi mật khẩu thành công.'})

class NotificationCursorPagination(CursorPagination):
    page_size = 20
    max_page_size = 100
    ordering = '-id'

class NotificationListView(ListAPIView):
    """Lists a company's notifications. Retrieving a page marks those
    notifications as read for the current user — matches the "retrieving
    counts as read" rule (the other way to mark read is the explicit
    NotificationMarkReadView below).
    """

    serializer_class = NotificationSerializer
    permission_classes = (IsAuthenticated, MatchesCompanyHeader)
    pagination_class = NotificationCursorPagination

    def get_queryset(self):
        user = self.request.user
        return Notification.objects.visible_to(user).annotate(
            is_read=Exists(NotificationRead.objects.filter(notification_id=OuterRef('pk'), user=user)),
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        items = page if page is not None else queryset

        NotificationRead.objects.bulk_create(
            [NotificationRead(notification_id=item.pk, user=request.user) for item in items],
            ignore_conflicts=True,
        )

        serializer = self.get_serializer(items, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

class NotificationMarkReadView(APIView):
    """Explicitly marks notifications as read (the 'click read' path).

    Body: {"ids": [1, 2, 3]}. Omit or send an empty list to mark every
    currently-unread notification for the company as read.
    """

    permission_classes = (IsAuthenticated, MatchesCompanyHeader)

    def post(self, request, *args, **kwargs):
        ids = request.data.get('ids') or []
        queryset = Notification.objects.visible_to(request.user)
        if ids:
            queryset = queryset.filter(pk__in=ids)
        pks = list(queryset.exclude(reads__user=request.user).values_list('pk', flat=True))

        NotificationRead.objects.bulk_create(
            [NotificationRead(notification_id=pk, user=request.user) for pk in pks],
            ignore_conflicts=True,
        )
        return Response({'marked_read': len(pks)})
