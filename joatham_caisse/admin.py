from django.contrib import admin

from .models import Caisse, MouvementCaisse, SessionCaisse, ValidationCaisse


@admin.register(Caisse)
class CaisseAdmin(admin.ModelAdmin):
    list_display = ("nom", "code", "entreprise", "devise", "est_active", "date_creation")
    list_filter = ("est_active", "devise", "entreprise")
    search_fields = ("nom", "code", "entreprise__nom")
    date_hierarchy = "date_creation"


@admin.register(SessionCaisse)
class SessionCaisseAdmin(admin.ModelAdmin):
    list_display = ("caisse", "entreprise", "statut", "utilisateur_ouverture", "date_ouverture", "date_fermeture")
    list_filter = ("statut", "entreprise", "caisse")
    search_fields = ("caisse__nom", "caisse__code", "entreprise__nom", "utilisateur_ouverture__username")
    date_hierarchy = "date_ouverture"


@admin.register(MouvementCaisse)
class MouvementCaisseAdmin(admin.ModelAdmin):
    list_display = ("libelle", "type_mouvement", "montant", "devise", "caisse", "session", "statut", "date_mouvement")
    list_filter = ("type_mouvement", "statut", "devise", "entreprise", "caisse")
    search_fields = ("libelle", "reference", "source_app", "source_model", "caisse__nom", "entreprise__nom")
    date_hierarchy = "date_mouvement"


@admin.register(ValidationCaisse)
class ValidationCaisseAdmin(admin.ModelAdmin):
    list_display = ("session", "entreprise", "decision", "validee_par", "date_validation")
    list_filter = ("decision", "entreprise")
    search_fields = ("session__caisse__nom", "entreprise__nom", "validee_par__username")
    date_hierarchy = "date_validation"

