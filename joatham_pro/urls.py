from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

from core.language_views import set_language_preference
from core.views import super_admin_audit_list, super_admin_company_deactivate, super_admin_company_list, super_admin_dashboard, super_admin_exchange_rate_list, super_admin_settings, super_admin_subscription_list, super_admin_subscription_manual_payment, super_admin_user_list

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='login', permanent=False), name='root_redirect'),
    path('i18n/setlang/', set_language_preference, name='set_language'),
    path('i18n/', include('django.conf.urls.i18n')),
    path('admin/', admin.site.urls),
    path('super-admin/', super_admin_dashboard, name='super_admin_dashboard'),
    path('super-admin/entreprises/', super_admin_company_list, name='super_admin_company_list'),
    path('super-admin/abonnements/', super_admin_subscription_list, name='super_admin_subscription_list'),
    path('super-admin/abonnements/<int:entreprise_id>/paiement-manuel/', super_admin_subscription_manual_payment, name='super_admin_subscription_manual_payment'),
    path('super-admin/utilisateurs/', super_admin_user_list, name='super_admin_user_list'),
    path('super-admin/audit/', super_admin_audit_list, name='super_admin_audit_list'),
    path('super-admin/parametres/', super_admin_settings, name='super_admin_settings'),
    path('super-admin/taux-change/', super_admin_exchange_rate_list, name='super_admin_exchange_rate_list'),
    path('super-admin/entreprises/<int:entreprise_id>/desactiver/', super_admin_company_deactivate, name='super_admin_company_deactivate'),

    path('', include('joatham_dashboard.urls')),  # accueil
    path('audit/', include('core.urls')),
    path('abonnement/', include('core.subscription_urls')),
    path('entreprise/', include('core.company_urls')),
    path('utilisateurs/', include('joatham_users.urls')),

    path('clients/', include('joatham_clients.urls')),
    path('services/', include('joatham_billing.service_urls')),
    path('factures/', include('joatham_billing.urls')),
    path('depenses/', include('joatham_depenses.urls')),
    path('produits/', include('joatham_products.urls')),
    path('compta/', include('joatham_comptabilite.urls')),
    path('apprenants/', include('joatham_apprenants.urls')),
]

if getattr(settings, "REST_FRAMEWORK_AVAILABLE", False):
    urlpatterns.append(path("api/", include("core.api_urls")))

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
