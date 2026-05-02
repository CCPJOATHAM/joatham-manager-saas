import os
import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


def message_attachment_upload_to(instance, filename):
    filename = os.path.basename(filename or "piece-jointe")
    extension = os.path.splitext(filename)[1]
    unique_name = f"{uuid.uuid4().hex}{extension}"
    message = instance.message
    conversation = message.conversation
    return f"messages/entreprise_{conversation.entreprise_id}/conversation_{conversation.id}/{unique_name}"


class Conversation(models.Model):
    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    sujet = models.CharField(max_length=180)
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="message_conversations",
        blank=True,
    )
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="conversations_creees",
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_modification", "-id"]
        indexes = [
            models.Index(fields=["entreprise", "-date_modification"]),
        ]

    def __str__(self):
        return self.sujet


class Message(models.Model):
    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="messages_internes",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    expediteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="messages_envoyes",
    )
    contenu = models.TextField()
    lecteurs = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="messages_lus",
        blank=True,
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_creation", "id"]
        indexes = [
            models.Index(fields=["entreprise", "date_creation"]),
            models.Index(fields=["conversation", "date_creation"]),
        ]

    def __str__(self):
        return f"{self.expediteur} - {self.conversation}"

    def save(self, *args, **kwargs):
        if self.conversation_id and self.entreprise_id != self.conversation.entreprise_id:
            self.entreprise = self.conversation.entreprise
        super().save(*args, **kwargs)


class MessageAttachment(models.Model):
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="pieces_jointes",
    )
    fichier = models.FileField(upload_to=message_attachment_upload_to)
    nom_original = models.CharField(max_length=255)
    type_contenu = models.CharField(max_length=120, blank=True, default="")
    taille = models.PositiveIntegerField(default=0)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.nom_original


class SuggestionSuperAdmin(models.Model):
    class Statut(models.TextChoices):
        NOUVEAU = "nouveau", _("Nouveau")
        EN_COURS = "en_cours", _("En cours")
        TRAITE = "traite", _("Traite")
        REJETE = "rejete", _("Rejete")
        ARCHIVE = "archive", _("Archive")

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="suggestions_super_admin",
    )
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="suggestions_super_admin",
    )
    sujet = models.CharField(max_length=180)
    message = models.TextField()
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.NOUVEAU)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    date_traitement = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_creation", "-id"]
        indexes = [
            models.Index(fields=["statut", "-date_creation"]),
            models.Index(fields=["entreprise", "-date_creation"]),
        ]

    def __str__(self):
        return self.sujet


class PublicQuestion(models.Model):
    class Statut(models.TextChoices):
        NOUVEAU = "nouveau", _("Nouveau")
        EN_COURS = "en_cours", _("En cours")
        TRAITE = "traite", _("Traite")
        REJETE = "rejete", _("Rejete")
        ARCHIVE = "archive", _("Archive")

    class LeadStatus(models.TextChoices):
        NOUVEAU = "nouveau", _("Nouveau")
        EN_COURS = "en_cours", _("En cours")
        CONVERTI = "converti", _("Converti")

    nom = models.CharField(max_length=150)
    email = models.EmailField()
    telephone = models.CharField(max_length=50, blank=True, default="")
    entreprise = models.CharField(max_length=150, blank=True, default="")
    sujet = models.CharField(max_length=180)
    message = models.TextField()
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.NOUVEAU)
    lead_status = models.CharField(max_length=20, choices=LeadStatus.choices, default=LeadStatus.NOUVEAU)
    is_lead = models.BooleanField(default=True)
    source = models.CharField(max_length=50, default="question_publique")
    invitation = models.ForeignKey(
        "joatham_users.EntrepriseInvitation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="public_questions",
    )
    reponse = models.TextField(blank=True)
    date_reponse = models.DateTimeField(null=True, blank=True)
    repondu_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="questions_publiques_repondues",
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    date_traitement = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_creation", "-id"]
        indexes = [
            models.Index(fields=["statut", "-date_creation"]),
            models.Index(fields=["email", "-date_creation"]),
        ]

    def __str__(self):
        return f"{self.nom} - {self.sujet}"
