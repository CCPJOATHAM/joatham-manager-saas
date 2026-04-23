from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('email-verification/', views.email_verification_sent_view, name='email_verification_sent'),
    path('email-verification/resend/', views.email_verification_resend_view, name='email_verification_resend'),
    path('email-verification/confirm/<uidb64>/<token>/', views.email_verification_confirm_view, name='email_verification_confirm'),
    path('password-reset/', views.SecurePasswordResetRequestView.as_view(), name='password_reset'),
    path('password-reset/done/', views.SecurePasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', views.SecurePasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', views.SecurePasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('proprietaire-dashboard/', views.admin_dashboard, name='proprietaire_dashboard'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('gestion-dashboard/', views.gestion_dashboard, name='gestion_dashboard'),
    path('comptable-dashboard/', views.comptable_dashboard, name='comptable_dashboard'),
    path('expire/', views.abonnement_expire, name='abonnement_expire'),
]
