from django.urls import path

from .views import (
    BankCardDetailView,
    BankCardListCreateView,
    BankCardSetPrimaryView,
    ChangePasswordView,
    ChatSummaryView,
    CompanyView,
    ContactListView,
    DepartmentDetailView,
    DepartmentListCreateView,
    MeView,
    NotificationListView,
    NotificationMarkReadView,
    OrgChartView,
    PositionDetailView,
    PositionListCreateView,
    ProfileUpdateView,
    RegisterView,
    UserAssignmentView,
)

app_name = 'accounts'
urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('me/', MeView.as_view(), name='me'),
    path('me/profile/', ProfileUpdateView.as_view(), name='profile-update'),
    path('company/', CompanyView.as_view(), name='company'),
    path('contact/', ContactListView.as_view(), name='contact'),
    path('chat/', ChatSummaryView.as_view(), name='chat'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('notifications/', NotificationListView.as_view(), name='notifications'),
    path('notifications/mark-read/', NotificationMarkReadView.as_view(), name='notifications-mark-read'),
    path('bank-cards/', BankCardListCreateView.as_view(), name='bank-cards'),
    path('bank-cards/<int:pk>/', BankCardDetailView.as_view(), name='bank-card-detail'),
    path('bank-cards/<int:pk>/set-primary/', BankCardSetPrimaryView.as_view(), name='bank-card-set-primary'),
    path('departments/', DepartmentListCreateView.as_view(), name='departments'),
    path('departments/<int:pk>/', DepartmentDetailView.as_view(), name='department-detail'),
    path('positions/', PositionListCreateView.as_view(), name='positions'),
    path('positions/<int:pk>/', PositionDetailView.as_view(), name='position-detail'),
    path('org-chart/', OrgChartView.as_view(), name='org-chart'),
    path('users/<int:user_id>/assignment/', UserAssignmentView.as_view(), name='user-assignment'),
]
