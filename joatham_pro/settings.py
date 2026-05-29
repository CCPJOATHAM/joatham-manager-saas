import importlib.util
import os
import warnings
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _


BASE_DIR = Path(__file__).resolve().parent.parent
REST_FRAMEWORK_AVAILABLE = importlib.util.find_spec("rest_framework") is not None


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-dev-key")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"
PASSWORD_MIN_LENGTH = int(os.getenv("DJANGO_PASSWORD_MIN_LENGTH", "10"))


def _env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _env_float(name, default=0.0):
    raw_value = os.getenv(name, str(default))
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        warnings.warn(f"{name} doit etre un nombre. Valeur par defaut utilisee.", RuntimeWarning)
        return default


def _build_allowed_hosts():
    configured_hosts = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if host.strip()]
    if configured_hosts:
        return configured_hosts

    if DEBUG:
        return ["127.0.0.1", "localhost", "[::1]"]

    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS doit être défini quand DJANGO_DEBUG=False. "
        "Exemple : DJANGO_ALLOWED_HOSTS=app.joatham.com,www.app.joatham.com"
    )


ALLOWED_HOSTS = _build_allowed_hosts()

if not DEBUG and SECRET_KEY == "django-insecure-dev-key":
    raise ImproperlyConfigured("DJANGO_SECRET_KEY doit etre defini avec une valeur secrete en production.")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core.apps.CoreConfig",
    "joatham_users.apps.JoathamUsersConfig",
    "joatham_dashboard",
    "joatham_clients",
    "joatham_billing",
    "joatham_messages.apps.JoathamMessagesConfig",
    "joatham_depenses",
    "joatham_comptabilite",
    "joatham_products.apps.JoathamProductsConfig",
    "joatham_apprenants.apps.JoathamApprenantsConfig",
    "joatham_caisse.apps.JoathamCaisseConfig",
    "joatham_payments.apps.JoathamPaymentsConfig",
    "joatham_rh.apps.JoathamRhConfig",
]

if REST_FRAMEWORK_AVAILABLE:
    INSTALLED_APPS.append("rest_framework")


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.UserLanguageMiddleware",
    "core.middleware.PlatformMaintenanceMiddleware",
    "joatham_dashboard.middleware.EmailVerificationRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "joatham_dashboard.middleware.ActiveSessionSecurityMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "joatham_pro.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.entreprise_identity",
            ],
        },
    },
]

WSGI_APPLICATION = "joatham_pro.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": os.getenv("DJANGO_DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.getenv("DJANGO_DB_NAME", str(BASE_DIR / "db.sqlite3")),
        "USER": os.getenv("DJANGO_DB_USER", ""),
        "PASSWORD": os.getenv("DJANGO_DB_PASSWORD", ""),
        "HOST": os.getenv("DJANGO_DB_HOST", ""),
        "PORT": os.getenv("DJANGO_DB_PORT", ""),
        "CONN_MAX_AGE": int(os.getenv("DJANGO_DB_CONN_MAX_AGE", "60")),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": PASSWORD_MIN_LENGTH},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "core.validators.PasswordComplexityValidator"},
]

LANGUAGE_CODE = os.getenv("DJANGO_LANGUAGE_CODE", "fr")
LANGUAGES = [
    ("fr", _("Français")),
    ("en", _("English")),
    ("pt", _("Português")),
    ("es", _("Español")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
LANGUAGE_COOKIE_NAME = "joatham_language"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Africa/Kinshasa")
USE_I18N = True
USE_TZ = True

STATIC_URL = os.getenv("DJANGO_STATIC_URL", "/static/")
STATIC_ROOT = Path(os.getenv("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles")))
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = os.getenv("DJANGO_MEDIA_URL", "/media/")
MEDIA_ROOT = Path(os.getenv("DJANGO_MEDIA_ROOT", str(BASE_DIR / "media")))
AUTH_USER_MODEL = "joatham_users.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SESSION_COOKIE_SECURE = _env_bool("DJANGO_SESSION_COOKIE_SECURE", False)
SESSION_COOKIE_AGE = int(os.getenv("DJANGO_SESSION_COOKIE_AGE", "1800"))
SESSION_SAVE_EVERY_REQUEST = _env_bool("DJANGO_SESSION_SAVE_EVERY_REQUEST", True)
SESSION_EXPIRE_AT_BROWSER_CLOSE = _env_bool("DJANGO_SESSION_EXPIRE_AT_BROWSER_CLOSE", True)
CSRF_COOKIE_SECURE = _env_bool("DJANGO_CSRF_COOKIE_SECURE", False)
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = _env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if _env_bool("DJANGO_USE_X_FORWARDED_PROTO", False) else None
LOGIN_URL = "login"

# Email configuration:
# - DEBUG=True: console backend by default
# - DEBUG=False: SMTP backend by default
# - no secret is hardcoded, everything sensitive comes from environment variables
DEFAULT_EMAIL_BACKEND = (
    "django.core.mail.backends.console.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_BACKEND = os.getenv("DJANGO_EMAIL_BACKEND", DEFAULT_EMAIL_BACKEND)
EMAIL_HOST = os.getenv("DJANGO_EMAIL_HOST", "smtp.office365.com")
EMAIL_PORT = int(os.getenv("DJANGO_EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("DJANGO_EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("DJANGO_EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_USE_SSL = os.getenv("DJANGO_EMAIL_USE_SSL", "False").lower() == "true"
EMAIL_TIMEOUT = int(os.getenv("DJANGO_EMAIL_TIMEOUT", "30"))
DEFAULT_FROM_EMAIL = os.getenv(
    "DJANGO_DEFAULT_FROM_EMAIL",
    EMAIL_HOST_USER or "JOATHAM Manager <no-reply@joatham-manager.local>",
)
PASSWORD_RESET_TIMEOUT = int(os.getenv("DJANGO_PASSWORD_RESET_TIMEOUT", "3600"))
PASSWORD_RESET_REQUEST_COOLDOWN = int(os.getenv("DJANGO_PASSWORD_RESET_REQUEST_COOLDOWN", "60"))
EMAIL_VERIFICATION_TIMEOUT = int(
    os.getenv("DJANGO_EMAIL_VERIFICATION_TIMEOUT", str(PASSWORD_RESET_TIMEOUT))
)

JOATHAM_PDF_ENGINE = os.getenv("JOATHAM_PDF_ENGINE", "xhtml2pdf")
JOATHAM_BILLING_PAGE_SIZE = int(os.getenv("JOATHAM_BILLING_PAGE_SIZE", "20"))
JOATHAM_FACTURE_NUMBER_FORMAT = os.getenv("JOATHAM_FACTURE_NUMBER_FORMAT", "standard")
JOATHAM_AUTO_PAYMENT_ENABLED = _env_bool("JOATHAM_AUTO_PAYMENT_ENABLED", False)
JOATHAM_PAYMENT_PROVIDER = os.getenv("JOATHAM_PAYMENT_PROVIDER", "").strip()
JOATHAM_PAYMENT_PUBLIC_KEY = os.getenv("JOATHAM_PAYMENT_PUBLIC_KEY", "").strip()
JOATHAM_PAYMENT_SECRET_KEY = os.getenv("JOATHAM_PAYMENT_SECRET_KEY", "").strip()
JOATHAM_PAYMENT_WEBHOOK_SECRET = os.getenv("JOATHAM_PAYMENT_WEBHOOK_SECRET", "").strip()
JOATHAM_PAYMENT_SANDBOX = _env_bool("JOATHAM_PAYMENT_SANDBOX", True)
JOATHAM_PAYMENT_CALLBACK_URL = os.getenv("JOATHAM_PAYMENT_CALLBACK_URL", "").strip()
JOATHAM_PAYMENT_RETURN_URL = os.getenv("JOATHAM_PAYMENT_RETURN_URL", "").strip()
JOATHAM_PAYMENT_CHANNELS = os.getenv("JOATHAM_PAYMENT_CHANNELS", "").strip()
JOATHAM_PAYMENT_CURRENCY = os.getenv("JOATHAM_PAYMENT_CURRENCY", "").strip().upper()
JOATHAM_PAYMENT_HTTP_TIMEOUT = _env_float("JOATHAM_PAYMENT_HTTP_TIMEOUT", 20.0)
CINETPAY_SITE_ID = os.getenv("CINETPAY_SITE_ID", JOATHAM_PAYMENT_PUBLIC_KEY).strip()
CINETPAY_APIKEY = os.getenv("CINETPAY_APIKEY", JOATHAM_PAYMENT_SECRET_KEY).strip()
CINETPAY_SECRET_KEY = os.getenv("CINETPAY_SECRET_KEY", JOATHAM_PAYMENT_WEBHOOK_SECRET).strip()
CINETPAY_CURRENCY = os.getenv("CINETPAY_CURRENCY", JOATHAM_PAYMENT_CURRENCY).strip().upper()
CINETPAY_CHANNELS = os.getenv("CINETPAY_CHANNELS", JOATHAM_PAYMENT_CHANNELS or "MOBILE_MONEY").strip().upper()
CINETPAY_PAYMENT_URL = os.getenv("CINETPAY_PAYMENT_URL", "https://api-checkout.cinetpay.com/v2/payment").strip()
CINETPAY_PAYMENT_CHECK_URL = os.getenv("CINETPAY_PAYMENT_CHECK_URL", "https://api-checkout.cinetpay.com/v2/payment/check").strip()
HEALTH_CHECK_TOKEN = os.getenv("HEALTH_CHECK_TOKEN", "").strip()

if REST_FRAMEWORK_AVAILABLE:
    REST_FRAMEWORK = {
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework.authentication.SessionAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
        ],
        "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
        "PAGE_SIZE": JOATHAM_BILLING_PAGE_SIZE,
    }

SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
SENTRY_ENVIRONMENT = os.getenv("SENTRY_ENVIRONMENT", "production" if not DEBUG else "development")
SENTRY_TRACES_SAMPLE_RATE = _env_float("SENTRY_TRACES_SAMPLE_RATE", 0.0)

if SENTRY_DSN:
    if importlib.util.find_spec("sentry_sdk") is None:
        warnings.warn(
            "SENTRY_DSN est defini mais sentry-sdk n'est pas installe. "
            "Le monitoring Sentry reste desactive.",
            RuntimeWarning,
        )
    else:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=SENTRY_ENVIRONMENT,
            integrations=[DjangoIntegration()],
            traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
            send_default_pii=False,
        )


LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO").upper()
DJANGO_LOG_LEVEL = os.getenv("DJANGO_DJANGO_LOG_LEVEL", "INFO").upper()
DJANGO_SECURITY_LOG_LEVEL = os.getenv("DJANGO_SECURITY_LOG_LEVEL", "WARNING").upper()
DJANGO_REQUEST_LOG_LEVEL = os.getenv("DJANGO_REQUEST_LOG_LEVEL", "ERROR").upper()
ROOT_LOG_LEVEL = os.getenv("DJANGO_ROOT_LOG_LEVEL", "WARNING").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": ROOT_LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": DJANGO_LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": DJANGO_REQUEST_LOG_LEVEL,
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": DJANGO_SECURITY_LOG_LEVEL,
            "propagate": False,
        },
        "django.core.mail": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "core.audit": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "core.health": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "joatham_dashboard": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "core": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "joatham_messages": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "joatham_billing": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "joatham_clients": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "joatham_users": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "joatham_products": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "joatham_comptabilite": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "joatham_apprenants": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
