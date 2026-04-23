from decimal import Decimal

from django.db import models
from django.utils import timezone


class Apprenant(models.Model):
    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="apprenants",
    )
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100, blank=True, default="")
    telephone = models.CharField(max_length=30, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    adresse = models.CharField(max_length=255, blank=True, default="")
    date_inscription = models.DateField(default=timezone.now)
    actif = models.BooleanField(default=True)
    observations = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["nom", "prenom", "id"]

    def __str__(self):
        full_name = f"{self.nom} {self.prenom}".strip()
        return full_name or f"Apprenant #{self.pk}"


class Formation(models.Model):
    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="formations",
    )
    nom = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    prix = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    duree = models.CharField(max_length=100, blank=True, default="")
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom", "id"]

    def __str__(self):
        return self.nom


class InscriptionFormation(models.Model):
    class Statut(models.TextChoices):
        EN_COURS = "en_cours", "En cours"
        TERMINEE = "terminee", "Terminee"
        ANNULEE = "annulee", "Annulee"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="inscriptions_formations",
    )
    apprenant = models.ForeignKey(
        Apprenant,
        on_delete=models.CASCADE,
        related_name="inscriptions",
    )
    formation = models.ForeignKey(
        Formation,
        on_delete=models.CASCADE,
        related_name="inscriptions",
    )
    facture = models.ForeignKey(
        "joatham_billing.Facture",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inscriptions_formations",
    )
    date_inscription = models.DateField(default=timezone.now)
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_COURS)
    montant_prevu = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    montant_paye = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    solde = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-date_inscription", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["entreprise", "apprenant", "formation"],
                name="uniq_inscription_formation_par_entreprise",
            ),
        ]

    def save(self, *args, **kwargs):
        self.solde = Decimal(self.montant_prevu or 0) - Decimal(self.montant_paye or 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.apprenant} - {self.formation}"


class PaiementInscription(models.Model):
    class ModePaiement(models.TextChoices):
        ESPECES = "especes", "Especes"
        VIREMENT = "virement", "Virement"
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        CHEQUE = "cheque", "Cheque"
        AUTRE = "autre", "Autre"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="paiements_inscriptions",
    )
    inscription = models.ForeignKey(
        InscriptionFormation,
        on_delete=models.CASCADE,
        related_name="paiements",
    )
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    date_paiement = models.DateField(default=timezone.now)
    mode_paiement = models.CharField(
        max_length=20,
        choices=ModePaiement.choices,
        default=ModePaiement.ESPECES,
    )
    reference = models.CharField(max_length=100, blank=True, default="")
    observations = models.TextField(blank=True, default="")
    utilisateur = models.ForeignKey(
        "joatham_users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paiements_apprenants",
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_paiement", "-date_creation", "-id"]

    def __str__(self):
        return f"Paiement {self.inscription_id} - {self.montant}"
