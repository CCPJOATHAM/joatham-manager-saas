from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Abonnement, AbonnementEntreprise, Entreprise, EntrepriseInvitation, User


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
    list_display = ("username", "email", "role", "preferred_language", "entreprise", "is_active", "is_staff")
    list_filter = ("role", "preferred_language", "entreprise", "is_active", "is_staff")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Organisation", {"fields": ("role", "preferred_language", "entreprise")}),
    )


@admin.register(EntrepriseInvitation)
class EntrepriseInvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "source", "is_used", "created_at", "expires_at", "reminder_count", "max_reminders", "last_reminder_sent_at")
    list_filter = ("is_used", "source", "created_at", "expires_at")
    search_fields = ("email", "full_name", "source")
    readonly_fields = ("created_at", "last_reminder_sent_at", "reminder_count")
    exclude = ("token",)
