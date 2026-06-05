from django.urls import path

from . import views
from joatham_billing.views import print_settings_view


urlpatterns = [
    path("", views.company_settings, name="company_settings"),
    path("impression/", print_settings_view, name="print_settings"),
]
