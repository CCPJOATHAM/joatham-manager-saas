from django.urls import path

from . import views

urlpatterns = [
    path("", views.subscription_overview, name="subscription_overview"),
    path("plans/", views.subscription_plan_list, name="subscription_plan_list"),
    path("paiement/", views.subscription_payment_create, name="subscription_payment_create"),
    path("paiement/automatique/<int:plan_id>/", views.subscription_payment_automatic_start, name="subscription_payment_automatic_start"),
    path("paiement/retour/", views.subscription_payment_return, name="subscription_payment_return"),
    path("historique/", views.subscription_payment_history, name="subscription_payment_history"),
    path("paiement/<int:payment_id>/", views.subscription_payment_detail, name="subscription_payment_detail"),
    path("paiement/<int:payment_id>/verifier/", views.subscription_payment_check, name="subscription_payment_check"),
    path("paiement/<int:payment_id>/justificatif/", views.subscription_payment_evidence, name="subscription_payment_evidence"),
    path("gestion/paiement/<int:payment_id>/justificatif/", views.subscription_payment_evidence_admin, name="subscription_payment_evidence_admin"),
    path("webhooks/<str:provider>/", views.subscription_payment_webhook, name="subscription_payment_webhook"),
]
