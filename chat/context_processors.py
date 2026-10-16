from .services import unread_count


def chat_unread(request):
    """Unread message counter for the header badge (one COUNT query, authenticated users only)."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    return {'chat_unread_count': unread_count(user)}
