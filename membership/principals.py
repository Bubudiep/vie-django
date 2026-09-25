class CustomerPrincipal:
    """Duck-typed stand-in for scope['user'] in the WebSocket consumer when a
    connection authenticates as a store.Customer (member) rather than an
    accounts.User (staff) — see accounts.channels_auth.get_user_from_token.
    Only the attributes chat.consumers.ChatConsumer actually reads are here.
    """

    principal_kind = 'customer'

    def __init__(self, customer):
        self.customer = customer
        self.pk = customer.pk
        self.id = customer.pk
        self.company_id = customer.company_id
        self.is_authenticated = True
        self.username = customer.name
