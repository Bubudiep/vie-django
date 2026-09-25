import logging

from rest_framework.permissions import SAFE_METHODS, BasePermission

logger = logging.getLogger(__name__)

COMPANY_ID_HEADER = 'X-Company-Id'


class MatchesCompanyHeader(BasePermission):
    message = "Missing or mismatched 'X-Company-Id' header."

    def has_permission(self, request, view):
        company_id = request.headers.get(COMPANY_ID_HEADER)
        user = request.user
        if not company_id or not user.is_authenticated or not user.company_id:
            logger.warning('Company header check failed: user=%r company_id=%r', user, company_id)
            return False
        if user.company_id != company_id:
            logger.warning('Company header mismatch: user_id=%s user.company_id=%r header=%r', user.pk, user.company_id, company_id)
            return False
        return True


def is_company_admin(user):
    from .models import Role
    return bool(getattr(user, 'role_id', None) and user.role.name == Role.ADMIN)


class IsCompanyAdminOrReadOnly(BasePermission):
    """Anyone in the company can read the org structure (departments,
    positions); only an admin can create/edit/delete it or reassign a
    member's department/position."""

    message = 'Chỉ quản trị viên được thực hiện thao tác này.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return is_company_admin(request.user)
