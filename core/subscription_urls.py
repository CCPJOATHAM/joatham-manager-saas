from django.urls import path

from . import views

urlpatterns = [
    path("", views.subscription_overview, name="subscription_overview"),
    path("plans/", views.subscription_plan_list, name="subscription_plan_list"),
    path("paiement/", views.subscription_payment_create, name="subscription_payment_create"),
]
