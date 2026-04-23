from django.contrib import admin
from .models import Facture
from .models import Facture, LigneFacture
from .models import Service

admin.site.register(Facture)
admin.site.register(LigneFacture)
admin.site.register(Service)