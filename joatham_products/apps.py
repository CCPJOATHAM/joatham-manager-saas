from django.utils.translation import gettext_lazy
from django.apps import AppConfig


class JoathamProductsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "joatham_products"
    verbose_name = gettext_lazy("Produits")
