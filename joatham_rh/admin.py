from django.contrib import admin

from .models import AvanceSalaire, DemandeConge, DocumentRH, Employe, PaiementSalaire, Poste, Presence


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


@admin.register(DemandeConge)
class DemandeCongeAdmin(admin.ModelAdmin):
    list_display = ("employe", "entreprise", "type_conge", "date_debut", "date_fin", "statut")
    list_filter = ("type_conge", "statut", "entreprise")
    search_fields = ("employe__matricule", "employe__nom", "employe__prenom", "motif", "entreprise__nom")


@admin.register(DocumentRH)
class DocumentRHAdmin(admin.ModelAdmin):
    list_display = ("titre", "employe", "entreprise", "type_document", "date_document")
    list_filter = ("type_document", "entreprise")
    search_fields = ("titre", "description", "employe__matricule", "employe__nom", "employe__prenom", "entreprise__nom")


@admin.register(AvanceSalaire)
class AvanceSalaireAdmin(admin.ModelAdmin):
    list_display = ("employe", "entreprise", "date_avance", "montant", "statut", "mode_paiement")
    list_filter = ("statut", "mode_paiement", "date_avance", "entreprise")
    search_fields = ("employe__matricule", "employe__nom", "employe__prenom", "reference", "motif")


@admin.register(PaiementSalaire)
class PaiementSalaireAdmin(admin.ModelAdmin):
    list_display = ("employe", "entreprise", "periode_mois", "periode_annee", "montant_net_a_payer", "montant_paye", "statut")
    list_filter = ("statut", "periode_annee", "periode_mois", "entreprise")
    search_fields = ("employe__matricule", "employe__nom", "employe__prenom", "reference", "notes")
