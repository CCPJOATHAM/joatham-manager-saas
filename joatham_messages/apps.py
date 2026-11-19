from django.utils.translation import gettext_lazy
from django.apps import AppConfig


class JoathamMessagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "joatham_messages"
    verbose_name = gettext_lazy("Messagerie JOATHAM")
