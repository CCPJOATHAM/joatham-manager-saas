from django.urls import path

from . import views


urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("add/", views.product_create, name="product_create"),
    path("<int:product_id>/edit/", views.product_update, name="product_update"),
]
