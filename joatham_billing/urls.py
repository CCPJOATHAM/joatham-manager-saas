from django.urls import path
from . import views

urlpatterns = [
    path('', views.facture_list, name='facture_list'),
    path('add/', views.add_facture, name='add_facture'),
    path('<int:id>/edit/', views.edit_facture, name='edit_facture'),
    path('<int:id>/', views.facture_detail, name='facture_detail'),
    path('<int:id>/statut/', views.change_facture_status_view, name='change_facture_status'),
    path('<int:id>/paiements/add/', views.add_paiement_facture, name='add_paiement_facture'),
    path('payer/<int:id>/', views.payer_facture, name='payer_facture'),
    path('pdf/<int:id>/', views.facture_pdf, name='facture_pdf'),
]
