from django.shortcuts import redirect
from django.urls import resolve, reverse


ALLOWED_UNVERIFIED_URL_NAMES = {
    "home",
    "login",
    "logout",
    "signup",
    "password_reset",
    "password_reset_done",
    "password_reset_confirm",
    "password_reset_complete",
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
