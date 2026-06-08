import re

from django.conf import settings
from django.contrib.auth.views import redirect_to_login


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "GLOBAL_LOGIN_REQUIRED", False):
            return self.get_response(request)

        if getattr(request, "user", None) and request.user.is_authenticated:
            return self.get_response(request)

        if self._is_ignored_path(request.path):
            return self.get_response(request)

        return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

    def _is_ignored_path(self, path: str) -> bool:
        static_url = getattr(settings, "STATIC_URL", "") or ""
        media_url = getattr(settings, "MEDIA_URL", "") or ""

        if static_url and path.startswith(static_url):
            return True
        if media_url and path.startswith(media_url):
            return True

        for pattern in getattr(settings, "LOGIN_REQUIRED_IGNORE_PATHS", []):
            if re.match(pattern, path):
                return True

        return False