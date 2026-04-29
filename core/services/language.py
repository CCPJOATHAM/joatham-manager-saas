from django.conf import settings


LANGUAGE_SESSION_KEY = "_language"
DEFAULT_LANGUAGE_CODE = "fr"


def get_supported_language_codes():
    return {code for code, _label in getattr(settings, "LANGUAGES", ())}


def normalize_language_code(language_code, fallback=DEFAULT_LANGUAGE_CODE):
    value = (language_code or "").strip().lower()
    if "-" in value:
        value = value.split("-", 1)[0]
    return value if value in get_supported_language_codes() else fallback


def resolve_language_code(language_code):
    value = (language_code or "").strip().lower()
    if "-" in value:
        value = value.split("-", 1)[0]
    return value if value in get_supported_language_codes() else None


def get_request_language(request):
    session_language = request.session.get(LANGUAGE_SESSION_KEY)
    cookie_language = request.COOKIES.get(getattr(settings, "LANGUAGE_COOKIE_NAME", "django_language"))
    user_language = ""

    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        user_language = getattr(user, "preferred_language", "")

    if user_language:
        candidates = (user_language, session_language, cookie_language, settings.LANGUAGE_CODE)
    else:
        candidates = (session_language, cookie_language, settings.LANGUAGE_CODE)

    for candidate in candidates:
        language_code = resolve_language_code(candidate)
        if language_code:
            return language_code

    return DEFAULT_LANGUAGE_CODE


def persist_language_preference(request, language_code):
    language_code = resolve_language_code(language_code)
    if not language_code:
        return None

    request.session[LANGUAGE_SESSION_KEY] = language_code

    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False) and hasattr(user, "preferred_language"):
        if user.preferred_language != language_code:
            user.preferred_language = language_code
            user.save(update_fields=["preferred_language"])

    return language_code
