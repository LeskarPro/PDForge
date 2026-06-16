from django.shortcuts import redirect
from django.urls import reverse

from . import sync_service


class SyncStartupMiddleware:
    """Runs the OneDrive/backup-folder startup check once, on the first
    request handled by this process.

    If the local DB and the remote backup both changed since the last
    sync, every request is redirected to the conflict-resolution page
    until the user picks "keep local" or "pull from backup".
    """

    _checked = False
    _conflict = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        cls = SyncStartupMiddleware

        if not cls._checked:
            cls._checked = True
            result = sync_service.startup_check()
            if result.get("action") == "conflict":
                cls._conflict = True

        if cls._conflict:
            conflict_url = reverse("core:sync_conflict")
            allowed_prefixes = (conflict_url, "/static/", "/media/")
            if not any(request.path.startswith(p) for p in allowed_prefixes):
                return redirect(conflict_url)

        return self.get_response(request)
