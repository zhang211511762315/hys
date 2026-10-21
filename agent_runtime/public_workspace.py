"""Explicit public workspace, with no account creation during request handling."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponseNotFound, HttpResponseRedirect, JsonResponse

USERNAME = "schoolsearch-public"


def enabled():
    return bool(getattr(settings, "PUBLIC_WORKSPACE_ENABLED", False))


def identity():
    return get_user_model().objects.get(username=USERNAME, is_active=True, is_staff=True, is_superuser=False)


def shared_user(user):
    return enabled() and user.is_authenticated and user.get_username() == USERNAME


def visible(qs, user):
    return qs if shared_user(user) else qs.filter(user=user)


class PublicWorkspaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.public_workspace = enabled()
        if request.public_workspace:
            path = request.path_info
            if path.startswith('/accounts/') or path in {'/account/delete/', '/admin/login/', '/admin/logout/', '/admin/password_change/'}:
                if request.method in {'GET', 'HEAD'}:
                    return HttpResponseRedirect('/projects/hys/')
                return HttpResponseNotFound()
            if path.startswith('/admin/auth/') or path.startswith('/admin/sessions/'):
                return HttpResponseNotFound()
            try:
                request.user = identity()
            except get_user_model().DoesNotExist:
                return JsonResponse({'error': 'public workspace unavailable'}, status=503)
            # Async decorators and views must see exactly the same identity.
            request._cached_user = request.user
            request._acached_user = request.user
            async def auser():
                return request.user
            request.auser = auser
        return self.get_response(request)
