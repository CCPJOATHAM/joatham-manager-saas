from django.contrib import admin

from .models import Apprenant, Formation, InscriptionFormation, PaiementInscription


@admin.register(Apprenant)
class ApprenantAdmin(admin.ModelAdmin):
    list_display = ("nom", "prenom", "entreprise", "telephone", "actif", "date_inscription")
    list_filter = ("entreprise", "actif")
    search_fields = ("nom", "prenom", "telephone", "email")


@admin.register(Formation)
class FormationAdmin(admin.ModelAdmin):
    list_display = ("nom", "entreprise", "prix", "duree", "actif")
    list_filter = ("entreprise", "actif")
    search_fields = ("nom",)


@admin.register(InscriptionFormation)
class InscriptionFormationAdmin(admin.ModelAdmin):
    list_display = (
        "apprenant",
        "formation",
        "entreprise",
        "date_inscription",
        "statut",
        "montant_prevu",
        "montant_paye",
        "solde",
    )
    list_filter = ("entreprise", "statut")
    search_fields = ("apprenant__nom", "apprenant__prenom", "formation__nom")


@admin.register(PaiementInscription)
class PaiementInscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "inscription",
        "entreprise",
        "montant",
        "date_paiement",
        "mode_paiement",
        "utilisateur",
    )
    list_filter = ("entreprise", "mode_paiement", "date_paiement")
    search_fields = ("reference", "inscription__apprenant__nom", "inscription__formation__nom")
