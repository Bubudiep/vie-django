import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .permissions import COMPANY_ID_HEADER

logger = logging.getLogger(__name__)


class CompanyScopedBackend(ModelBackend):
    """Authenticates by (username, company) instead of a globally unique username.

    The company is read from the 'X-Company-Id' header, so the same username can
    exist in multiple companies. A request without the header only matches users
    that have no company (e.g. platform admins).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        UserModel = get_user_model()
        company_id = request.headers.get(COMPANY_ID_HEADER) if request is not None else None
        try:
            user = UserModel._default_manager.get(username=username, company_id=company_id)
        except UserModel.DoesNotExist:
            logger.warning('Login failed: unknown username=%r for company_id=%r', username, company_id)
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            logger.error('Login failed: multiple users for username=%r company_id=%r', username, company_id)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            logger.info('Login success: user_id=%s username=%r company_id=%r', user.pk, username, company_id)
            return user
        logger.warning('Login failed: bad password or inactive user_id=%s username=%r company_id=%r', user.pk, username, company_id)
        return None
