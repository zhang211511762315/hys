"""Research authentication runs before CSRF, without exempting authenticated writes."""
import ipaddress
from django.conf import settings
from django.http import JsonResponse


class ResearchAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if (path == '/api/v1/research-runs' or path.startswith('/api/v1/research-runs/')) and not request.user.is_authenticated:
            return JsonResponse({'error': 'authentication required'}, status=401)
        return self.get_response(request)


def client_ip(request):
    remote = request.META.get('REMOTE_ADDR', '')
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return 'unknown'
    trusted = {str(ipaddress.ip_address(v)) for v in settings.TRUSTED_PROXY_IPS}
    if str(address) in trusted:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '').strip()
        # A trusted proxy must replace the header with exactly one address.
        if forwarded and ',' not in forwarded:
            try:
                return str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
    return str(address)
