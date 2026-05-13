from django.urls import path

from . import views


urlpatterns = [
    path("", views.payment_list, name="payment_list"),
    path("nouveau/", views.payment_create, name="payment_create"),
    path("rapports/", views.payment_reports, name="payment_reports"),
    path("rapports/export/excel/", views.payment_export_excel, name="payment_export_excel"),
    path("rapports/export/pdf/", views.payment_reports_pdf, name="payment_reports_pdf"),
    path("<int:payment_id>/", views.payment_detail, name="payment_detail"),
    path("<int:payment_id>/confirmer/", views.payment_confirm, name="payment_confirm"),
    path("<int:payment_id>/rejeter/", views.payment_reject, name="payment_reject"),
    path("<int:payment_id>/annuler/", views.payment_cancel, name="payment_cancel"),
]

