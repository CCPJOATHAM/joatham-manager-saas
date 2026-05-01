import logging

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.http import require_safe


logger = logging.getLogger(__name__)


def _health_response(payload, *, status=200):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def health_check(request):
    return _health_response({"status": "ok"})


def _is_database_health_authorized(request):
    expected_token = getattr(settings, "HEALTH_CHECK_TOKEN", "")
    if not expected_token:
        return True
    provided_token = request.headers.get("X-Health-Token") or request.GET.get("token", "")
    return constant_time_compare(provided_token, expected_token)


@require_safe
def database_health_check(request):
    if not _is_database_health_authorized(request):
        return _health_response({"status": "forbidden"}, status=403)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        logger.warning("health.db.failed error_class=%s", exc.__class__.__name__)
        return _health_response({"status": "error"}, status=503)
    return _health_response({"status": "ok"})
