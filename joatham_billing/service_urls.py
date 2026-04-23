from django.urls import path

from . import service_views


urlpatterns = [
    path("", service_views.service_list, name="service_list"),
    path("add/", service_views.service_create, name="service_create"),
    path("<int:service_id>/edit/", service_views.service_update, name="service_update"),
    path("<int:service_id>/toggle-status/", service_views.service_toggle_status, name="service_toggle_status"),
]
