from django.contrib import messages
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse

from joatham_users.services.session_security import (
    SESSION_EXPIRED_MESSAGE,
    SESSION_REPLACED_MESSAGE,
    get_request_session_cookie_key,
    is_session_key_active,
    release_active_session_by_key,
    logout_and_release_session,
    validate_or_register_current_session,
)


ALLOWED_UNVERIFIED_URL_NAMES = {
    "home",
    "public_home",
    "login",
    "login_session_conflict",
    "logout",
    "set_language",
    "signup",
    "password_reset",
    "password_reset_done",
    "password_reset_confirm",
    "password_reset_complete",
    "public_question_create",
    "public_question_thanks",
    "email_verification_sent",
    "email_verification_confirm",
    "email_verification_resend",
}


class EmailVerificationRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return self.get_response(request)

        if getattr(user, "is_superuser", False) or getattr(user, "email_verified", True):
            return self.get_response(request)

        if request.path.startswith("/admin/") or request.path.startswith("/static/") or request.path.startswith("/media/"):
            return self.get_response(request)

        match = resolve(request.path_info)
        if match.url_name in ALLOWED_UNVERIFIED_URL_NAMES:
            return self.get_response(request)

        return redirect(reverse("email_verification_sent"))


SESSION_SECURITY_EXEMPT_URL_NAMES = ALLOWED_UNVERIFIED_URL_NAMES | {
    "health_check",
    "database_health_check",
}

SESSION_SECURITY_EXEMPT_PREFIXES = (
    "/admin/",
    "/static/",
    "/media/",
)


def _is_session_security_exempt_path(request):
    path = request.path or ""
    if path == "/":
        return True
    if any(path.startswith(prefix) for prefix in SESSION_SECURITY_EXEMPT_PREFIXES):
        return True
    try:
        match = resolve(request.path_info)
    except Resolver404:
        return False
    return match.url_name in SESSION_SECURITY_EXEMPT_URL_NAMES


class ActiveSessionSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _is_session_security_exempt_path(request):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            validation_state = validate_or_register_current_session(request)
            if validation_state == "conflict":
                logout_and_release_session(request)
                messages.warning(request, SESSION_REPLACED_MESSAGE)
                return redirect(reverse("login"))
            if validation_state == "expired":
                logout_and_release_session(request)
                messages.warning(request, SESSION_EXPIRED_MESSAGE)
                return redirect(reverse("login"))
            return self.get_response(request)

        session_cookie_key = get_request_session_cookie_key(request)
        if session_cookie_key and not is_session_key_active(session_cookie_key):
            release_active_session_by_key(session_cookie_key)
            messages.warning(request, SESSION_EXPIRED_MESSAGE)
            return redirect(reverse("login"))

        return self.get_response(request)
