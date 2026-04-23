from django.contrib import admin

from .models import CompteComptable, EcritureComptable, ExerciceComptable, JournalComptable, LigneEcritureComptable


@admin.register(ExerciceComptable)
class ExerciceComptableAdmin(admin.ModelAdmin):
    list_display = ("code", "entreprise", "date_debut", "date_fin", "statut")
    list_filter = ("statut", "entreprise")
    search_fields = ("code", "entreprise__nom")


@admin.register(CompteComptable)
class CompteComptableAdmin(admin.ModelAdmin):
    list_display = ("numero", "nom", "entreprise", "classe", "categorie", "sens_normal", "actif")
    list_filter = ("entreprise", "classe", "categorie", "actif")
    search_fields = ("numero", "nom", "entreprise__nom")


@admin.register(JournalComptable)
class JournalComptableAdmin(admin.ModelAdmin):
    list_display = ("code", "nom", "entreprise", "type_journal", "actif")
    list_filter = ("entreprise", "type_journal", "actif")
    search_fields = ("code", "nom", "entreprise__nom")


class LigneEcritureInline(admin.TabularInline):
    model = LigneEcritureComptable
    extra = 0


@admin.register(EcritureComptable)
class EcritureComptableAdmin(admin.ModelAdmin):
    list_display = ("numero_piece", "entreprise", "journal", "date_piece", "libelle", "statut")
    list_filter = ("entreprise", "journal", "statut")
    search_fields = ("numero_piece", "libelle", "source_model", "source_event")
    inlines = [LigneEcritureInline]


@admin.register(LigneEcritureComptable)
class LigneEcritureComptableAdmin(admin.ModelAdmin):
    list_display = ("ecriture", "compte", "libelle", "debit", "credit")
    list_filter = ("compte__entreprise", "compte")
    search_fields = ("ecriture__numero_piece", "libelle", "compte__numero", "compte__nom")
