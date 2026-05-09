from django.urls import path

from . import views


urlpatterns = [
    path("", views.caisse_list, name="caisse_list"),
    path("sessions/", views.session_list, name="caisse_session_list"),
    path("mouvements/", views.movement_list, name="caisse_movement_list"),
    path("mouvements/export/excel/", views.movement_export_excel, name="caisse_movement_export_excel"),
    path("rapports/", views.cash_reports, name="caisse_reports"),
    path("rapports/export/pdf/", views.cash_reports_export_pdf, name="caisse_reports_export_pdf"),
    path("nouvelle/", views.caisse_create, name="caisse_create"),
    path("<int:caisse_id>/", views.caisse_detail, name="caisse_detail"),
    path("<int:caisse_id>/ouvrir/", views.open_session_view, name="caisse_open_session"),
    path("session/<int:session_id>/", views.session_detail, name="caisse_session_detail"),
    path("session/<int:session_id>/fermer/", views.close_session_view, name="caisse_close_session"),
    path("session/<int:session_id>/mouvement/", views.add_movement_view, name="caisse_add_movement"),
    path("session/<int:session_id>/valider/", views.validate_session_view, name="caisse_validate_session"),
    path("session/<int:session_id>/rejeter/", views.reject_session_view, name="caisse_reject_session"),
]
