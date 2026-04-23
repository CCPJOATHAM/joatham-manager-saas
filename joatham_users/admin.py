from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Abonnement, AbonnementEntreprise, Entreprise, User


@admin.register(Entreprise)
class EntrepriseAdmin(admin.ModelAdmin):
    list_display = ("id", "nom", "abonnement", "date_expiration")
    search_fields = ("nom", "raison_sociale", "email")


@admin.register(Abonnement)
class AbonnementAdmin(admin.ModelAdmin):
    list_display = ("id", "nom", "code", "prix", "duree_jours", "actif")


@admin.register(AbonnementEntreprise)
class AbonnementEntrepriseAdmin(admin.ModelAdmin):
    list_display = ("entreprise", "plan", "statut", "date_debut", "date_fin", "essai", "actif")
    list_filter = ("statut", "essai", "actif")
    search_fields = ("entreprise__nom", "plan__nom", "plan__code")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "role", "entreprise", "is_active", "is_staff")
    list_filter = ("role", "entreprise", "is_active", "is_staff")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Organisation", {"fields": ("role", "entreprise")}),
    )
