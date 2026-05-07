from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from joatham_users.models import UserActiveSession


SESSION_EXPIRED_MESSAGE = _("Votre session a expiré après 30 minutes d’inactivité. Veuillez vous reconnecter.")
SESSION_CONFLICT_MESSAGE = _(
    "Ce compte est déjà connecté sur un autre appareil. Veuillez d’abord vous déconnecter de l’autre session."
)
SESSION_REPLACED_MESSAGE = _("Votre session n’est plus active sur cet appareil. Veuillez vous reconnecter.")


@dataclass(frozen=True)
class SingleSessionLoginResult:
    allowed: bool
    user: object = None
    message: object = None


def _delete_expired_session(session_key):
    if not session_key:
        return
    Session.objects.filter(session_key=session_key, expire_date__lte=timezone.now()).delete()


def is_session_key_active(session_key):
    if not session_key:
        return False
    _delete_expired_session(session_key)
    return Session.objects.filter(session_key=session_key, expire_date__gt=timezone.now()).exists()


def get_request_session_key(request):
    return getattr(getattr(request, "session", None), "session_key", None)


def get_request_session_cookie_key(request):
    return request.COOKIES.get(settings.SESSION_COOKIE_NAME, "")


def login_with_single_active_session(request, user):
    UserModel = get_user_model()
    backend = getattr(user, "backend", None)

    with transaction.atomic():
        locked_user = UserModel.objects.select_for_update().get(pk=user.pk)
        active_session = UserActiveSession.objects.select_for_update().filter(user=locked_user).first()

        if active_session and is_session_key_active(active_session.session_key):
            return SingleSessionLoginResult(False, locked_user, SESSION_CONFLICT_MESSAGE)

        if backend:
            locked_user.backend = backend

        auth_login(request, locked_user)
        request.session.save()
        session_key = get_request_session_key(request)
        now = timezone.now()

        if active_session:
            active_session.session_key = session_key
            active_session.created_at = now
            active_session.last_seen_at = now
            active_session.save(update_fields=["session_key", "created_at", "last_seen_at"])
        else:
            UserActiveSession.objects.create(
                user=locked_user,
                session_key=session_key,
                created_at=now,
                last_seen_at=now,
            )

    return SingleSessionLoginResult(True, locked_user, None)


def release_active_session(user, session_key=None):
    if not user or not getattr(user, "is_authenticated", False):
        return

    queryset = UserActiveSession.objects.filter(user=user)
    if session_key:
        queryset = queryset.filter(session_key=session_key)
    queryset.delete()


def release_active_session_by_key(session_key):
    if session_key:
        UserActiveSession.objects.filter(session_key=session_key).delete()


def logout_and_release_session(request):
    user = getattr(request, "user", None)
    session_key = get_request_session_key(request)
    release_active_session(user, session_key=session_key)
    auth_logout(request)


def validate_or_register_current_session(request):
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return "anonymous"

    session_key = get_request_session_key(request)
    if not session_key:
        return "expired"

    UserModel = get_user_model()
    now = timezone.now()

    with transaction.atomic():
        locked_user = UserModel.objects.select_for_update().get(pk=user.pk)
        active_session = UserActiveSession.objects.select_for_update().filter(user=locked_user).first()

        if active_session is None:
            UserActiveSession.objects.create(
                user=locked_user,
                session_key=session_key,
                created_at=now,
                last_seen_at=now,
            )
            return "active"

        if active_session.session_key == session_key:
            active_session.last_seen_at = now
            active_session.save(update_fields=["last_seen_at"])
            return "active"

        if not is_session_key_active(active_session.session_key):
            active_session.session_key = session_key
            active_session.created_at = now
            active_session.last_seen_at = now
            active_session.save(update_fields=["session_key", "created_at", "last_seen_at"])
            return "active"

    return "conflict"
