from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.utils.encoding import force_bytes
from django.utils.http import base36_to_int, urlsafe_base64_decode, urlsafe_base64_encode

from core.audit import record_audit_event
from joatham_users.models import User


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.password}{user.email_verified}{timestamp}"

    def check_token(self, user, token):
        if not (user and token):
            return False

        try:
            ts_b36, _hash = token.split("-")
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False

        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(
                self._make_token_with_timestamp(user, ts, secret),
                token,
            ):
                break
        else:
            return False

        timeout_seconds = getattr(settings, "EMAIL_VERIFICATION_TIMEOUT", getattr(settings, "PASSWORD_RESET_TIMEOUT", 3600))
        if (self._num_seconds(self._now()) - ts) > timeout_seconds:
            return False

        return True


email_verification_token_generator = EmailVerificationTokenGenerator()


def build_email_verification_url(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token_generator.make_token(user)
    path = reverse("email_verification_confirm", kwargs={"uidb64": uid, "token": token})
    return request.build_absolute_uri(path)


def send_email_verification(request, user):
    verification_url = build_email_verification_url(request, user)
    if hasattr(request, "session") and getattr(settings, "DEBUG", False):
        request.session["debug_email_verification_url"] = verification_url
    context = {
        "user": user,
        "verification_url": verification_url,
        "app_name": "JOATHAM Manager",
        "expiration_seconds": getattr(settings, "EMAIL_VERIFICATION_TIMEOUT", getattr(settings, "PASSWORD_RESET_TIMEOUT", 3600)),
    }
    subject = render_to_string("registration/email_verification_subject.txt", context).strip()
    text_body = render_to_string("registration/email_verification_email.txt", context)
    html_body = render_to_string("registration/email_verification_email.html", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(html_body, "text/html")
    message.send()

    entreprise = getattr(user, "entreprise", None)
    if entreprise is not None:
        record_audit_event(
            entreprise=entreprise,
            utilisateur=user,
            action="email_verification_sent",
            module="auth",
            objet_type="User",
            objet_id=user.id,
            description=f"Email de confirmation envoye a {user.email}.",
            metadata={"email": user.email},
        )


def get_user_from_uid(uidb64):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        return User.objects.get(pk=uid)
    except Exception:
        return None


def verify_email_token(*, uidb64, token):
    user = get_user_from_uid(uidb64)
    if user is None:
        return None
    if not email_verification_token_generator.check_token(user, token):
        return None
    return user
