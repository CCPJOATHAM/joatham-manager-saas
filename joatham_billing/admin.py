from django.contrib import admin
from .models import EntreprisePrintSettings, Facture, LigneFacture, Service

admin.site.register(Facture)
admin.site.register(LigneFacture)
admin.site.register(Service)
admin.site.register(EntreprisePrintSettings)
