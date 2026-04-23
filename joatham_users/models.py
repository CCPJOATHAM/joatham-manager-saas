from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class Entreprise(models.Model):
    class ReferentielComptable(models.TextChoices):
        SYSCOHADA = "syscohada", "SYSCOHADA"
        PCG = "pcg", "PCG"
        IFRS_SIMPLIFIE = "ifrs_simplifie", "IFRS simplifie"
        AUTRE = "autre", "Autre"

    nom = models.CharField(max_length=100)
    raison_sociale = models.CharField(max_length=150, blank=True, default="")
    adresse = models.CharField(max_length=255, blank=True, default="")
    ville = models.CharField(max_length=100, blank=True, default="Matadi")
    pays = models.CharField(max_length=100, blank=True, default="RDC")
    telephone = models.CharField(max_length=50, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    logo = models.ImageField(upload_to="entreprises/logos/", blank=True, null=True)
    rccm = models.CharField(max_length=100, blank=True, default="")
    id_nat = models.CharField(max_length=100, blank=True, default="")
    numero_impot = models.CharField(max_length=100, blank=True, default="")
    banque = models.CharField(max_length=100, blank=True, default="")
    compte_bancaire = models.CharField(max_length=100, blank=True, default="")
    devise = models.CharField(max_length=10, default="CDF")
    taux_tva_defaut = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    referentiel_comptable = models.CharField(
        max_length=30,
        choices=ReferentielComptable.choices,
        default=ReferentielComptable.SYSCOHADA,
    )
    abonnement = models.ForeignKey(
        "Abonnement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    date_expiration = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.nom


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super admin"
        PROPRIETAIRE = "proprietaire", "Proprietaire"
        GESTIONNAIRE = "gestionnaire", "Gestionnaire"
        COMPTABLE = "comptable", "Comptable"

    ROLE_ALIASES = {
        "admin": Role.PROPRIETAIRE,
    }

    role = models.CharField(max_length=20, choices=Role.choices)
    telephone = models.CharField(max_length=50, blank=True, default="")
    email_verified = models.BooleanField(default=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    entreprise = models.ForeignKey(
        Entreprise,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.username

    @property
    def normalized_role(self):
        return self.ROLE_ALIASES.get(self.role, self.role)

    @property
    def is_proprietaire(self):
        return self.normalized_role == self.Role.PROPRIETAIRE

    @property
    def is_super_admin(self):
        return self.normalized_role == self.Role.SUPER_ADMIN

    def mark_email_verified(self):
        if self.email_verified:
            return
        self.email_verified = True
        self.email_verified_at = timezone.now()
        self.save(update_fields=["email_verified", "email_verified_at"])


class Abonnement(models.Model):
    nom = models.CharField(max_length=50)
    code = models.CharField(max_length=50, blank=True, default="")
    prix = models.FloatField()
    duree_jours = models.IntegerField()
    actif = models.BooleanField(default=True)
    description = models.TextField(blank=True, default="")

    def __str__(self):
        return self.nom


class AbonnementEntreprise(models.Model):
    class Statut(models.TextChoices):
        ESSAI = "essai", "Essai"
        ACTIF = "actif", "Actif"
        EXPIRE = "expire", "Expire"
        SUSPENDU = "suspendu", "Suspendu"

    entreprise = models.OneToOneField(
        Entreprise,
        on_delete=models.CASCADE,
        related_name="abonnement_entreprise",
    )
    plan = models.ForeignKey(
        Abonnement,
        on_delete=models.PROTECT,
        related_name="abonnements_entreprises",
    )
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.ACTIF)
    date_debut = models.DateField()
    date_fin = models.DateField()
    essai = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation", "-id"]

    def __str__(self):
        return f"{self.entreprise.nom} - {self.plan.nom} ({self.statut})"
