from django.urls import path
from . import views

urlpatterns = [
    path('', views.depenses_list, name='depenses'),
    path('depenses/pdf/', views.depenses_pdf, name='depenses_pdf'),
]