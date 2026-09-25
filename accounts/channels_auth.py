import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

logger = logging.getLogger(__name__)


@database_sync_to_async
def get_user_from_token(token):
    from oauth2_provider.models import get_access_token_model

    AccessToken = get_access_token_model()
    try:
        access_token = AccessToken.objects.select_related('user').get(token=token)
        if access_token.expires >= timezone.now():
            return access_token.user
    except AccessToken.DoesNotExist:
        pass

    # Not a staff OAuth2 token — try it as a member (store.Customer) token.
    from membership.models import CustomerToken
    from membership.principals import CustomerPrincipal

    try:
        customer_token = CustomerToken.objects.select_related('customer', 'customer__company').get(key=token)
        return CustomerPrincipal(customer_token.customer)
    except CustomerToken.DoesNotExist:
        return AnonymousUser()


class OAuth2TokenAuthMiddleware(BaseMiddleware):
    """Authenticates a WebSocket connection from a '?token=<access_token>' query param.

    The channel layer has no request headers to attach an Authorization
    bearer token to, so the OAuth2 access token is passed as a query string
    parameter instead and resolved to a user here.
    """

    async def __call__(self, scope, receive, send):
        query_string = parse_qs(scope.get('query_string', b'').decode())
        token = query_string.get('token', [None])[0]
        scope['user'] = await get_user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)
