from django.urls import path

from . import views


urlpatterns = [
    path("", views.user_list, name="user_list"),
    path("add/", views.user_create, name="user_create"),
    path("invite/", views.user_invite, name="user_invite"),
    path("invitations/<str:token>/accepter/", views.user_invitation_accept, name="user_invitation_accept"),
    path("invitations/<int:invitation_id>/resend/", views.user_invitation_resend, name="user_invitation_resend"),
    path("invitations/<int:invitation_id>/cancel/", views.user_invitation_cancel, name="user_invitation_cancel"),
    path("<int:user_id>/edit/", views.user_update, name="user_update"),
    path("<int:user_id>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
    path("<int:user_id>/remove-access/", views.user_remove_access, name="user_remove_access"),
    path("<int:user_id>/delete/", views.user_delete, name="user_delete"),
    path("<int:user_id>/", views.user_detail, name="user_detail"),
]
