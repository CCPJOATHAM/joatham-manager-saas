from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

from core.views import super_admin_dashboard

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='login', permanent=False), name='root_redirect'),
    path('admin/', admin.site.urls),
    path('super-admin/', super_admin_dashboard, name='super_admin_dashboard'),

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
