from rest_framework.permissions import BasePermission

from .models import CustomerToken


class IsCustomerAuthenticated(BasePermission):
    """request.user for these views is a store.Customer, which has no
    is_authenticated attribute — check that CustomerTokenAuthentication
    actually matched instead of using the default IsAuthenticated.
    """

    message = 'Cần đăng nhập.'

    def has_permission(self, request, view):
        return isinstance(request.auth, CustomerToken)
