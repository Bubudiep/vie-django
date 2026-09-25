from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def user_group_name(user_id):
    return f'user_{user_id}'


def customer_group_name(customer_id):
    return f'customer_{customer_id}'


def notify_company(company_id, payload):
    """Push a notification to every connection currently in a company's room."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        company_id,
        {'type': 'notification', 'payload': payload},
    )


def notify_user(user_id, payload):
    """Push a notification only to a specific user's own connections."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        user_group_name(user_id),
        {'type': 'notification', 'payload': payload},
    )


def notify_customer(customer_id, payload):
    """Push a notification only to a specific member's (store.Customer) own connections."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        customer_group_name(customer_id),
        {'type': 'notification', 'payload': payload},
    )


def room_group_name(room_id):
    return f'chatroom_{room_id}'


def notify_room(room_id, message_data):
    """Push a chat message to everyone currently viewing this specific room."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        room_group_name(room_id),
        {'type': 'chat_message', 'message': message_data},
    )
