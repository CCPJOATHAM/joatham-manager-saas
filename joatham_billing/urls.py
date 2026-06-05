from django.urls import path
from . import views

urlpatterns = [
    path('', views.facture_list, name='facture_list'),
    path('proformas/', views.proforma_list, name='proforma_list'),
    path('proformas/ajouter/', views.add_proforma, name='add_proforma'),
    path('proformas/<int:id>/', views.proforma_detail, name='proforma_detail'),
    path('proformas/<int:id>/modifier/', views.edit_proforma, name='edit_proforma'),
    path('proformas/<int:id>/pdf/', views.proforma_pdf, name='proforma_pdf'),
    path('proformas/<int:id>/annuler/', views.cancel_proforma_view, name='cancel_proforma'),
    path('proformas/<int:id>/convertir/', views.convert_proforma_view, name='convert_proforma'),
    path('add/', views.add_facture, name='add_facture'),
    path('<int:id>/edit/', views.edit_facture, name='edit_facture'),
    path('<int:id>/', views.facture_detail, name='facture_detail'),
    path('<int:id>/statut/', views.change_facture_status_view, name='change_facture_status'),
    path('<int:id>/paiements/add/', views.add_paiement_facture, name='add_paiement_facture'),
    path('payer/<int:id>/', views.payer_facture, name='payer_facture'),
    path('pdf/<int:id>/', views.facture_pdf, name='facture_pdf'),
]
