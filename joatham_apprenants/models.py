from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


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
        EN_COURS = "en_cours", _("En cours")
        TERMINEE = "terminee", _("Terminee")
        ANNULEE = "annulee", _("Annulee")

    class StatutPaiement(models.TextChoices):
        IMPAYE = "impaye", _("Non payé")
        PARTIEL = "partiel", _("Partiel")
        PAYE = "paye", _("Payé")

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
        self.solde = max(
            Decimal(self.montant_prevu or 0) - Decimal(self.montant_paye or 0),
            Decimal("0.00"),
        )
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and {"montant_prevu", "montant_paye"} & set(update_fields):
            kwargs["update_fields"] = set(update_fields) | {"solde"}
        super().save(*args, **kwargs)

    @property
    def statut_paiement(self):
        montant_prevu = Decimal(self.montant_prevu or 0)
        montant_paye = Decimal(self.montant_paye or 0)
        if montant_paye <= Decimal("0.00"):
            return self.StatutPaiement.IMPAYE
        if montant_paye < montant_prevu:
            return self.StatutPaiement.PARTIEL
        return self.StatutPaiement.PAYE

    @property
    def statut_paiement_label(self):
        return self.StatutPaiement(self.statut_paiement).label

    @property
    def trop_percu(self):
        return max(
            Decimal(self.montant_paye or 0) - Decimal(self.montant_prevu or 0),
            Decimal("0.00"),
        )

    def __str__(self):
        return f"{self.apprenant} - {self.formation}"


class PaiementInscription(models.Model):
    class ModePaiement(models.TextChoices):
        ESPECES = "especes", _("Especes")
        VIREMENT = "virement", _("Virement")
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        CHEQUE = "cheque", _("Cheque")
        AUTRE = "autre", _("Autre")

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


def recalculate_inscription_financial_totals(inscription):
    total_paye = (
        inscription.paiements.aggregate(total=Sum("montant"))["total"]
        or Decimal("0.00")
    )
    solde = max(
        Decimal(inscription.montant_prevu or 0) - Decimal(total_paye),
        Decimal("0.00"),
    )
    InscriptionFormation.objects.filter(id=inscription.id).update(
        montant_paye=total_paye,
        solde=solde,
    )
    inscription.montant_paye = total_paye
    inscription.solde = solde
    return inscription


@receiver(post_save, sender=PaiementInscription)
@receiver(post_delete, sender=PaiementInscription)
def sync_inscription_financial_totals(sender, instance, **kwargs):
    if instance.inscription_id:
        try:
            inscription = instance.inscription
        except InscriptionFormation.DoesNotExist:
            return
        recalculate_inscription_financial_totals(inscription)
