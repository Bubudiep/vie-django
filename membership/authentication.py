from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from .models import CustomerToken


class CustomerTokenAuthentication(BaseAuthentication):
    """Authorization: CToken <key> — the member (store.Customer) equivalent
    of the staff-facing OAuth2 bearer token. request.user ends up being the
    Customer instance itself (not an accounts.User), request.auth the token.
    """

    keyword = 'ctoken'

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != self.keyword.encode():
            return None
        if len(auth) != 2:
            raise AuthenticationFailed('Header Authorization không hợp lệ.')
        try:
            token = CustomerToken.objects.select_related('customer', 'customer__company').get(key=auth[1].decode())
        except CustomerToken.DoesNotExist:
            raise AuthenticationFailed('Token không hợp lệ hoặc đã hết hạn.')
        return (token.customer, token)

    def authenticate_header(self, request):
        return self.keyword
