from django.urls import path

from . import views


urlpatterns = [
    path("", views.employe_list, name="rh_employe_list"),
    path("employes/export/csv/", views.employe_export_csv, name="rh_employe_export_csv"),
    path("employes/imprimer/", views.employe_list_print, name="rh_employe_list_print"),
    path("employes/nouveau/", views.employe_create, name="rh_employe_create"),
    path("employes/<int:employe_id>/", views.employe_detail, name="rh_employe_detail"),
    path("employes/<int:employe_id>/imprimer/", views.employe_print, name="rh_employe_print"),
    path("employes/<int:employe_id>/modifier/", views.employe_update, name="rh_employe_update"),
    path("postes/", views.poste_list, name="rh_poste_list"),
    path("postes/nouveau/", views.poste_create, name="rh_poste_create"),
    path("presences/", views.presence_list, name="rh_presence_list"),
    path("presences/export/csv/", views.presence_export_csv, name="rh_presence_export_csv"),
    path("presences/nouveau/", views.presence_create, name="rh_presence_create"),
    path("avances/", views.avance_list, name="rh_avance_list"),
    path("avances/nouveau/", views.avance_create, name="rh_avance_create"),
    path("avances/<int:avance_id>/", views.avance_detail, name="rh_avance_detail"),
    path("avances/<int:avance_id>/annuler/", views.avance_cancel, name="rh_avance_cancel"),
    path("salaires/", views.salaire_list, name="rh_salaire_list"),
    path("salaires/nouveau/", views.salaire_create, name="rh_salaire_create"),
    path("salaires/<int:paiement_id>/", views.salaire_detail, name="rh_salaire_detail"),
    path("paie/rapport/", views.paie_report, name="rh_paie_report"),
    path("conges/", views.conge_list, name="rh_conge_list"),
    path("conges/export/csv/", views.conge_export_csv, name="rh_conge_export_csv"),
    path("conges/nouveau/", views.conge_create, name="rh_conge_create"),
    path("conges/<int:conge_id>/approuver/", views.conge_approve, name="rh_conge_approve"),
    path("conges/<int:conge_id>/refuser/", views.conge_refuse, name="rh_conge_refuse"),
    path("documents/", views.document_list, name="rh_document_list"),
    path("documents/export/csv/", views.document_export_csv, name="rh_document_export_csv"),
    path("documents/nouveau/", views.document_create, name="rh_document_create"),
    path("rapports/", views.rh_reports, name="rh_reports"),
    path("rapports/export/csv/", views.rh_reports_export_csv, name="rh_reports_export_csv"),
    path("rapports/imprimer/", views.rh_reports_print, name="rh_reports_print"),
]
