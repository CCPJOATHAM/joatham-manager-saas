from django.db import models
from joatham_users.models import Abonnement as SaaSPlan
from joatham_users.models import AbonnementEntreprise as SaaSSubscription


class ActivityLog(models.Model):
    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    utilisateur = models.ForeignKey(
        "joatham_users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    action = models.CharField(max_length=100)
    module = models.CharField(max_length=50)
    objet_type = models.CharField(max_length=100, blank=True, default="")
    objet_id = models.PositiveIntegerField(null=True, blank=True)
    description = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation", "-id"]
        indexes = [
            models.Index(fields=["entreprise", "module", "date_creation"]),
            models.Index(fields=["entreprise", "action", "date_creation"]),
            models.Index(fields=["entreprise", "utilisateur", "date_creation"]),
        ]

    def __str__(self):
        return f"{self.module}:{self.action}#{self.objet_id or '-'}"


class PaiementAbonnement(models.Model):
    class Duree(models.TextChoices):
        MENSUEL = "mensuel", "Mensuel"
        TRIMESTRIEL = "trimestriel", "Trimestriel"
        ANNUEL = "annuel", "Annuel"

    class Statut(models.TextChoices):
        EN_ATTENTE = "en_attente", "En attente"
        VALIDE = "valide", "Valide"
        REFUSE = "refuse", "Refuse"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="paiements_abonnement",
    )
    plan = models.ForeignKey(
        "joatham_users.Abonnement",
        on_delete=models.PROTECT,
        related_name="paiements_abonnement",
    )
    duree = models.CharField(max_length=20, choices=Duree.choices)
    montant = models.DecimalField(max_digits=12, decimal_places=2)
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE)
    reference_paiement = models.CharField(max_length=120)
    preuve_paiement = models.FileField(upload_to="abonnements/preuves/", blank=True, null=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_validation = models.DateTimeField(null=True, blank=True)
    valide_par = models.ForeignKey(
        "joatham_users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paiements_abonnement_valides",
    )

    class Meta:
        ordering = ["-date_creation", "-id"]
        indexes = [
            models.Index(fields=["entreprise", "statut", "date_creation"]),
            models.Index(fields=["statut", "date_creation"]),
        ]

    def __str__(self):
        return f"{self.entreprise.nom} - {self.plan.nom} - {self.get_statut_display()}"


class Plan(SaaSPlan):
    class Meta:
        proxy = True
        verbose_name = "Plan SaaS"
        verbose_name_plural = "Plans SaaS"


class Abonnement(SaaSSubscription):
    class Meta:
        proxy = True
        verbose_name = "Abonnement SaaS"
        verbose_name_plural = "Abonnements SaaS"
