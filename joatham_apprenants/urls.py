from django.urls import path

from . import views


urlpatterns = [
    path("dashboard/", views.apprenants_dashboard, name="apprenants_dashboard"),
    path("dashboard/export/pdf/", views.apprenants_dashboard_pdf, name="apprenants_dashboard_pdf"),
    path("dashboard/export/excel/", views.apprenants_dashboard_excel, name="apprenants_dashboard_excel"),
    path("", views.apprenant_list, name="apprenant_list"),
    path("export/pdf/", views.apprenants_pdf, name="apprenants_pdf"),
    path("export/excel/", views.apprenants_excel, name="apprenants_excel"),
    path("add/", views.apprenant_create, name="apprenant_create"),
    path("formations/", views.formation_list, name="formation_list"),
    path("formations/export/pdf/", views.formations_pdf, name="formations_pdf"),
    path("formations/export/excel/", views.formations_excel, name="formations_excel"),
    path("formations/add/", views.formation_create, name="formation_create"),
    path("formations/<int:formation_id>/edit/", views.formation_update, name="formation_update"),
    path("formations/<int:formation_id>/toggle-status/", views.formation_toggle_status, name="formation_toggle_status"),
    path("inscriptions/add/", views.inscription_create, name="inscription_create"),
    path("inscriptions/export/pdf/", views.inscriptions_pdf, name="inscriptions_pdf"),
    path("inscriptions/export/excel/", views.inscriptions_excel, name="inscriptions_excel"),
    path("inscriptions/<int:inscription_id>/", views.inscription_detail, name="inscription_detail"),
    path("inscriptions/<int:inscription_id>/facture/generate/", views.inscription_generate_facture, name="inscription_generate_facture"),
    path("inscriptions/<int:inscription_id>/facture/link/", views.inscription_link_existing_facture, name="inscription_link_existing_facture"),
    path("inscriptions/<int:inscription_id>/facture/unlink/", views.inscription_unlink_facture, name="inscription_unlink_facture"),
    path("inscriptions/<int:inscription_id>/paiements/export/pdf/", views.inscription_paiements_pdf, name="inscription_paiements_pdf"),
    path("inscriptions/<int:inscription_id>/paiements/export/excel/", views.inscription_paiements_excel, name="inscription_paiements_excel"),
    path("inscriptions/<int:inscription_id>/paiements/add/", views.paiement_inscription_create, name="paiement_inscription_create"),
]
