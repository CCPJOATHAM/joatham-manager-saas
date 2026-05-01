from django.contrib import admin

from .models import Conversation, Message, MessageAttachment, PublicQuestion, SuggestionSuperAdmin


class MessageAttachmentInline(admin.TabularInline):
    model = MessageAttachment
    extra = 0


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("sujet", "entreprise", "cree_par", "date_modification")
    list_filter = ("entreprise",)
    search_fields = ("sujet", "entreprise__nom", "cree_par__email", "cree_par__username")
    filter_horizontal = ("participants",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "expediteur", "date_creation")
    list_filter = ("conversation__entreprise",)
    search_fields = ("contenu", "expediteur__email", "expediteur__username", "conversation__sujet")
    inlines = [MessageAttachmentInline]


@admin.register(SuggestionSuperAdmin)
class SuggestionSuperAdminAdmin(admin.ModelAdmin):
    list_display = ("sujet", "entreprise", "utilisateur", "statut", "date_creation", "date_traitement")
    list_filter = ("statut", "entreprise")
    search_fields = ("sujet", "message", "entreprise__nom", "utilisateur__email")


@admin.register(PublicQuestion)
class PublicQuestionAdmin(admin.ModelAdmin):
    list_display = (
        "sujet",
        "nom",
        "email",
        "entreprise",
        "statut",
        "lead_status",
        "is_lead",
        "source",
        "repondu_par",
        "date_creation",
        "date_reponse",
        "date_traitement",
    )
    list_filter = ("statut", "lead_status", "is_lead", "source")
    search_fields = ("sujet", "message", "reponse", "nom", "email", "telephone", "entreprise", "repondu_par__email", "repondu_par__username")
