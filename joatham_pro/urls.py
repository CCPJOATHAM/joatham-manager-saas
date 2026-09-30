from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

from core.health import database_health_check, health_check
from core.language_views import set_language_preference
from core import reports_views
from core.views import super_admin_audit_list, super_admin_company_deactivate, super_admin_company_list, super_admin_dashboard, super_admin_exchange_rate_list, super_admin_settings, super_admin_subscription_list, super_admin_subscription_manual_payment, super_admin_user_list
from joatham_dashboard.views import public_home, public_robots_txt, public_sitemap_xml
from joatham_messages.views import public_question_create, public_question_success, public_question_thanks, send_public_question_invitation, super_admin_messages, super_admin_public_question_reply, update_lead_status
from joatham_users.views import profile_view

urlpatterns = [
    path('', public_home, name='public_home'),
    path('robots.txt', public_robots_txt, name='robots_txt'),
    path('sitemap.xml', public_sitemap_xml, name='sitemap_xml'),
    path('health/', health_check, name='health_check'),
    path('health/db/', database_health_check, name='database_health_check'),
    path('i18n/setlang/', set_language_preference, name='set_language'),
    path('i18n/', include('django.conf.urls.i18n')),
    path('question-avant-inscription/', public_question_create, name='public_question_create'),
    path('question-avant-inscription/merci/', public_question_thanks, name='public_question_thanks'),
    path('question-envoyee/', public_question_success, name='public_question_success'),
    path('admin/', admin.site.urls),
    path('super-admin/', super_admin_dashboard, name='super_admin_dashboard'),
    path('super-admin/entreprises/', super_admin_company_list, name='super_admin_company_list'),
    path('super-admin/abonnements/', super_admin_subscription_list, name='super_admin_subscription_list'),
    path('super-admin/abonnements/<int:entreprise_id>/paiement-manuel/', super_admin_subscription_manual_payment, name='super_admin_subscription_manual_payment'),
    path('super-admin/utilisateurs/', super_admin_user_list, name='super_admin_user_list'),
    path('super-admin/audit/', super_admin_audit_list, name='super_admin_audit_list'),
    path('super-admin/parametres/', super_admin_settings, name='super_admin_settings'),
    path('super-admin/taux-change/', super_admin_exchange_rate_list, name='super_admin_exchange_rate_list'),
    path('super-admin/messages/', super_admin_messages, name='super_admin_messages'),
    path('super-admin/messages/<int:id>/update-status/', update_lead_status, name='super_admin_update_lead_status'),
    path('super-admin/messages/<int:question_id>/send-invitation/', send_public_question_invitation, name='super_admin_send_public_question_invitation'),
    path('super-admin/questions-publiques/<int:question_id>/repondre/', super_admin_public_question_reply, name='super_admin_public_question_reply'),
    path('super-admin/entreprises/<int:entreprise_id>/desactiver/', super_admin_company_deactivate, name='super_admin_company_deactivate'),

    path('profil/', profile_view, name='profile'),
    path('', include('joatham_dashboard.urls')),  # accueil
    path('audit/', include('core.urls')),
    path('rapports-avances/', reports_views.advanced_reports, name='advanced_reports'),
    path('rapports-avances/export/excel/', reports_views.advanced_reports_export_excel, name='advanced_reports_export_excel'),
    path('rapports-avances/export/pdf/', reports_views.advanced_reports_export_pdf, name='advanced_reports_export_pdf'),
    path('abonnement/', include('core.subscription_urls')),
    path('entreprise/', include('core.company_urls')),
    path('utilisateurs/', include('joatham_users.urls')),
    path('messages/', include('joatham_messages.urls')),

    path('clients/', include('joatham_clients.urls')),
    path('services/', include('joatham_billing.service_urls')),
    path('factures/', include('joatham_billing.urls')),
    path('depenses/', include('joatham_depenses.urls')),
    path('caisse/', include('joatham_caisse.urls')),
    path('paiements/', include('joatham_payments.urls')),
    path('produits/', include('joatham_products.urls')),
    path('compta/', include('joatham_comptabilite.urls')),
    path('apprenants/', include('joatham_apprenants.urls')),
    path('rh/', include('joatham_rh.urls')),
]

if getattr(settings, "REST_FRAMEWORK_AVAILABLE", False):
    urlpatterns.append(path("api/", include("core.api_urls")))

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
