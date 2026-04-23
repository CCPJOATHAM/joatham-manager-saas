from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class ExerciceComptable(models.Model):
    class Statut(models.TextChoices):
        OUVERT = "ouvert", "Ouvert"
        FERME = "ferme", "Ferme"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="exercices_comptables",
    )
    code = models.CharField(max_length=20)
    date_debut = models.DateField()
    date_fin = models.DateField()
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.OUVERT)

    class Meta:
        ordering = ["-date_debut"]
        constraints = [
            models.UniqueConstraint(fields=["entreprise", "code"], name="uniq_exercice_code_entreprise"),
        ]

    def __str__(self):
        return f"{self.entreprise.nom} - {self.code}"


class CompteComptable(models.Model):
    class Sens(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="comptes_comptables",
    )
    numero = models.CharField(max_length=20)
    nom = models.CharField(max_length=120)
    classe = models.CharField(max_length=2)
    categorie = models.CharField(max_length=30)
    sens_normal = models.CharField(max_length=10, choices=Sens.choices)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["numero"]
        constraints = [
            models.UniqueConstraint(fields=["entreprise", "numero"], name="uniq_compte_numero_entreprise"),
        ]

    def __str__(self):
        return f"{self.numero} - {self.nom}"


class JournalComptable(models.Model):
    class TypeJournal(models.TextChoices):
        VENTES = "ventes", "Ventes"
        ACHATS = "achats", "Achats"
        TRESORERIE = "tresorerie", "Tresorerie"
        OD = "od", "Operations diverses"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="journaux_comptables",
    )
    code = models.CharField(max_length=20)
    nom = models.CharField(max_length=120)
    type_journal = models.CharField(max_length=20, choices=TypeJournal.choices)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["entreprise", "code"], name="uniq_journal_code_entreprise"),
        ]

    def __str__(self):
        return f"{self.code} - {self.nom}"


class EcritureComptable(models.Model):
    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        VALIDE = "valide", "Valide"
        ANNULEE = "annulee", "Annulee"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="ecritures_comptables",
    )
    exercice = models.ForeignKey(
        ExerciceComptable,
        on_delete=models.PROTECT,
        related_name="ecritures",
    )
    journal = models.ForeignKey(
        JournalComptable,
        on_delete=models.PROTECT,
        related_name="ecritures",
    )
    numero_piece = models.CharField(max_length=50)
    date_piece = models.DateField()
    libelle = models.CharField(max_length=255)
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.VALIDE)
    source_app = models.CharField(max_length=50, blank=True, default="")
    source_model = models.CharField(max_length=50, blank=True, default="")
    source_id = models.PositiveIntegerField(null=True, blank=True)
    source_event = models.CharField(max_length=50, blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_piece", "-id"]
        indexes = [
            models.Index(fields=["entreprise", "date_piece"]),
            models.Index(fields=["entreprise", "source_app", "source_model", "source_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["entreprise", "source_app", "source_model", "source_id", "source_event"],
                name="uniq_ecriture_source_event_entreprise",
                condition=Q(source_app__gt="", source_model__gt="", source_event__gt="", source_id__isnull=False),
            ),
        ]

    def __str__(self):
        return f"{self.numero_piece} - {self.libelle}"

    @property
    def total_debit(self):
        lignes = self._prefetched_objects_cache.get("lignes") if hasattr(self, "_prefetched_objects_cache") else None
        if lignes is None:
            lignes = self.lignes.all()
        return sum((Decimal(ligne.debit) for ligne in lignes), Decimal("0"))

    @property
    def total_credit(self):
        lignes = self._prefetched_objects_cache.get("lignes") if hasattr(self, "_prefetched_objects_cache") else None
        if lignes is None:
            lignes = self.lignes.all()
        return sum((Decimal(ligne.credit) for ligne in lignes), Decimal("0"))

    def est_equilibree(self):
        return self.total_debit == self.total_credit

    def clean(self):
        if self.pk and not self.est_equilibree():
            raise ValidationError("Une ecriture validee doit etre equilibree.")


class LigneEcritureComptable(models.Model):
    ecriture = models.ForeignKey(
        EcritureComptable,
        on_delete=models.CASCADE,
        related_name="lignes",
    )
    compte = models.ForeignKey(
        CompteComptable,
        on_delete=models.PROTECT,
        related_name="lignes_ecriture",
    )
    libelle = models.CharField(max_length=255, blank=True, default="")
    debit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.compte.numero} D:{self.debit} C:{self.credit}"

    def clean(self):
        if self.debit < 0 or self.credit < 0:
            raise ValidationError("Debit et credit doivent etre positifs.")
        if self.debit > 0 and self.credit > 0:
            raise ValidationError("Une ligne ne peut pas porter debit et credit en meme temps.")
        if self.debit == 0 and self.credit == 0:
            raise ValidationError("Une ligne doit porter un montant.")
