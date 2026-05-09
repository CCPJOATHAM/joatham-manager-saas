from django.urls import path

from . import views


urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("add/", views.product_create, name="product_create"),
    path("<int:product_id>/edit/", views.product_update, name="product_update"),
    path("stock/mouvements/", views.stock_movement_list, name="stock_movement_list"),
    path("stock/entree/", views.stock_entry_create, name="stock_entry_create"),
    path("stock/sortie/", views.stock_exit_create, name="stock_exit_create"),
    path("stock/ajustement/", views.stock_adjustment_create, name="stock_adjustment_create"),
]
