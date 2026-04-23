from django.urls import include, path

from joatham_apprenants.api.urls import urlpatterns as apprenants_api_urlpatterns
from joatham_billing.api.urls import urlpatterns as billing_api_urlpatterns
from joatham_clients.api.urls import urlpatterns as clients_api_urlpatterns
from joatham_depenses.api.urls import urlpatterns as depenses_api_urlpatterns


urlpatterns = [
    path("", include((clients_api_urlpatterns, "clients_api"))),
    path("", include((depenses_api_urlpatterns, "depenses_api"))),
    path("", include((billing_api_urlpatterns, "billing_api"))),
    path("", include((apprenants_api_urlpatterns, "apprenants_api"))),
]
