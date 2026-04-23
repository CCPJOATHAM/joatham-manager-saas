from django.urls import path

from . import views


urlpatterns = [
    path("", views.user_list, name="user_list"),
    path("add/", views.user_create, name="user_create"),
    path("<int:user_id>/edit/", views.user_update, name="user_update"),
    path("<int:user_id>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
    path("<int:user_id>/delete/", views.user_delete, name="user_delete"),
]
