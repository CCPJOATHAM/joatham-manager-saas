from django.urls import path

from . import views

urlpatterns = [
    path("", views.comptabilite_dashboard, name="compta_dashboard"),
    path("resultat/", views.compte_resultat, name="compte_resultat"),
    path("bilan/", views.bilan, name="bilan"),
    path("grand-livre/", views.grand_livre, name="grand_livre"),
    path("balance/", views.balance, name="balance"),
    path("export/<slug:report_slug>/<str:fmt>/", views.export_report, name="compta_report_export"),
]
