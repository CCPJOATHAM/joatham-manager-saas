from django.contrib import admin

from .models import Employe, Poste, Presence


@admin.register(Poste)
class PosteAdmin(admin.ModelAdmin):
    list_display = ("nom", "entreprise", "actif", "created_at")
    list_filter = ("actif", "entreprise")
    search_fields = ("nom", "entreprise__nom")


@admin.register(Employe)
class EmployeAdmin(admin.ModelAdmin):
    list_display = ("matricule", "nom", "prenom", "entreprise", "poste", "type_contrat", "statut", "actif")
    list_filter = ("statut", "type_contrat", "actif", "entreprise")
    search_fields = ("matricule", "nom", "prenom", "telephone", "email", "entreprise__nom")


@admin.register(Presence)
class PresenceAdmin(admin.ModelAdmin):
    list_display = ("employe", "entreprise", "date", "statut", "heure_arrivee", "heure_depart")
    list_filter = ("statut", "date", "entreprise")
    search_fields = ("employe__matricule", "employe__nom", "employe__prenom", "entreprise__nom")
