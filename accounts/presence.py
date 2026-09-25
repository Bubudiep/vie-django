from django.db.models import Count

from .models import User, UserSession


def register_session(user, channel_name):
    """Record a new live connection and return the user's total active session count."""
    UserSession.objects.create(user=user, channel_name=channel_name)
    return UserSession.objects.filter(user=user).count()


def unregister_session(channel_name):
    """Drop a connection. Returns (user_id, remaining_session_count), or (None, None) if unknown."""
    session = UserSession.objects.filter(channel_name=channel_name).first()
    if session is None:
        return None, None
    user_id = session.user_id
    session.delete()
    remaining = UserSession.objects.filter(user_id=user_id).count()
    return user_id, remaining


def online_users(company_id):
    """[{id, username, session_count}] for every user of a company with >=1 live connection."""
    qs = (
        User.objects.filter(company_id=company_id, sessions__isnull=False)
        .annotate(session_count=Count('sessions'))
        .distinct()
    )
    return [{'id': u.id, 'username': u.username, 'session_count': u.session_count} for u in qs]
