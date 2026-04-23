import hashlib

from django.conf import settings
from django.core.cache import cache


def get_request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _build_reset_cache_key(prefix, value):
    digest = hashlib.sha256((value or "").strip().lower().encode("utf-8")).hexdigest()
    return f"password_reset:{prefix}:{digest}"


def is_password_reset_throttled(*, email, ip_address):
    email_key = _build_reset_cache_key("email", email)
    ip_key = _build_reset_cache_key("ip", ip_address)
    return bool(cache.get(email_key) or cache.get(ip_key))


def mark_password_reset_request(*, email, ip_address):
    timeout = getattr(settings, "PASSWORD_RESET_REQUEST_COOLDOWN", 60)
    cache.set(_build_reset_cache_key("email", email), True, timeout)
    cache.set(_build_reset_cache_key("ip", ip_address), True, timeout)
