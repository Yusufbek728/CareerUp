from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import UserRateThrottle


class ChatReadThrottle(UserRateThrottle):
    """All chat API requests. Own scope, so it does not share a bucket with the listing throttles."""
    scope = 'chat_read'
    rate = '120/minute'


class ChatWriteThrottle(UserRateThrottle):
    """Only unsafe methods (sending messages, blocking, reporting)."""
    scope = 'chat_write'
    rate = '30/minute'

    def allow_request(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return super().allow_request(request, view)
