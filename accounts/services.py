from django.db import transaction

from .models import BankCard, Department


@transaction.atomic
def set_primary_bank_card(user, card):
    """Marks `card` as the user's primary bank card, unsetting any other."""
    BankCard.objects.select_for_update().filter(user=user, is_primary=True).exclude(pk=card.pk).update(is_primary=False)
    if not card.is_primary:
        card.is_primary = True
        card.save(update_fields=['is_primary'])
    return card


def update_avatar(profile, uploaded_file):
    """Processes an uploaded avatar (HD cap + blurred preview) and saves it
    onto `profile`. Falls back to storing the raw file if Pillow can't
    process it (unreadable image, Pillow missing)."""
    from chat.images import process_image

    processed, preview_data_url = process_image(uploaded_file, uploaded_file.name)
    profile.avatar = processed if processed is not None else uploaded_file
    profile.avatar_preview_data_url = preview_data_url
    profile.save(update_fields=['avatar', 'avatar_preview_data_url'])
    return profile


def update_cover(profile, uploaded_file):
    """Same HD-cap downscaling as the avatar, minus the blurred placeholder
    — a cover photo isn't shown before the rest of the page has data anyway,
    so there's no slow-connection paint to optimize for."""
    from chat.images import process_image

    processed, _ = process_image(uploaded_file, uploaded_file.name)
    profile.cover = processed if processed is not None else uploaded_file
    profile.save(update_fields=['cover'])
    return profile


def build_org_chart(company):
    """Nested department tree for the org chart: each node carries its head
    and member list, with children nested underneath. Two queries total
    (departments + active members), tree built in Python since a company's
    department count is small — no need for a recursive CTE.
    """
    departments = list(
        Department.objects.filter(company=company)
        .select_related('head')
        .prefetch_related('members__position')
    )
    by_parent = {}
    for dept in departments:
        by_parent.setdefault(dept.parent_id, []).append(dept)

    def member_data(user):
        return {
            'id': user.pk,
            'username': user.username,
            'full_name': f'{user.first_name} {user.last_name}'.strip(),
            'position': user.position.name if user.position_id else None,
        }

    def node(dept):
        members = [member_data(u) for u in dept.members.all() if u.is_active]
        return {
            'id': dept.pk,
            'name': dept.name,
            'head': member_data(dept.head) if dept.head_id else None,
            'members': members,
            'children': [node(child) for child in by_parent.get(dept.pk, [])],
        }

    return [node(dept) for dept in by_parent.get(None, [])]
