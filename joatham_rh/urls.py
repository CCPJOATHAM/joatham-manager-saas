from django.urls import path

from . import views


urlpatterns = [
    path("", views.employe_list, name="rh_employe_list"),
    path("employes/nouveau/", views.employe_create, name="rh_employe_create"),
    path("employes/<int:employe_id>/", views.employe_detail, name="rh_employe_detail"),
    path("employes/<int:employe_id>/modifier/", views.employe_update, name="rh_employe_update"),
    path("postes/", views.poste_list, name="rh_poste_list"),
    path("postes/nouveau/", views.poste_create, name="rh_poste_create"),
    path("presences/", views.presence_list, name="rh_presence_list"),
    path("presences/nouveau/", views.presence_create, name="rh_presence_create"),
]
