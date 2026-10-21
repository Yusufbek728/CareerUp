from django.http import Http404


class HideAdminMiddleware:
    """Django admin answers 404 to everyone except active superusers, so its URL can't be discovered."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/admin/'):
            user = request.user
            if not (user.is_active and user.is_superuser):
                raise Http404
        return self.get_response(request)
