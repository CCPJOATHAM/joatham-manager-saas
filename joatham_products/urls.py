from django.urls import path

from . import views


urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("add/", views.product_create, name="product_create"),
    path("<int:product_id>/edit/", views.product_update, name="product_update"),
    path("stock/mouvements/", views.stock_movement_list, name="stock_movement_list"),
    path("stock/rapports/", views.stock_reports, name="stock_reports"),
    path("stock/entree/", views.stock_entry_create, name="stock_entry_create"),
    path("stock/sortie/", views.stock_exit_create, name="stock_exit_create"),
    path("stock/ajustement/", views.stock_adjustment_create, name="stock_adjustment_create"),
    path("stock/mouvements/export/excel/", views.stock_movement_export_excel, name="stock_movement_export_excel"),
    path("stock/rapports/export/pdf/", views.stock_reports_export_pdf, name="stock_reports_export_pdf"),
    path("inventaires/", views.inventory_list, name="inventory_list"),
    path("inventaires/export/excel/", views.inventory_export_excel, name="inventory_export_excel"),
    path("inventaires/nouveau/", views.inventory_create, name="inventory_create"),
    path("inventaires/<int:pk>/", views.inventory_detail, name="inventory_detail"),
    path("inventaires/<int:pk>/compter/", views.inventory_count, name="inventory_count"),
    path("inventaires/<int:pk>/cloturer/", views.inventory_close, name="inventory_close"),
    path("inventaires/<int:pk>/valider/", views.inventory_validate, name="inventory_validate"),
    path("inventaires/<int:pk>/annuler/", views.inventory_cancel, name="inventory_cancel"),
]
