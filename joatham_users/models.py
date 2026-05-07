import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


LANGUAGE_CHOICES = (
    ("fr", _("Français")),
    ("en", _("English")),
    ("pt", _("Português")),
    ("es", _("Español")),
)


def generate_invitation_token():
    return secrets.token_urlsafe(32)


def default_invitation_expiry():
    return timezone.now() + timedelta(days=7)


class Entreprise(models.Model):
    class ReferentielComptable(models.TextChoices):
        SYSCOHADA = "syscohada", "SYSCOHADA"
        PCG = "pcg", "PCG"
        IFRS_SIMPLIFIE = "ifrs_simplifie", _("IFRS simplifie")
        AUTRE = "autre", _("Autre")

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
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.nom


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", _("Super admin")
        PROPRIETAIRE = "proprietaire", _("Proprietaire")
        GESTIONNAIRE = "gestionnaire", _("Gestionnaire")
        COMPTABLE = "comptable", _("Comptable")

    ROLE_ALIASES = {
        "admin": Role.PROPRIETAIRE,
    }

    role = models.CharField(max_length=20, choices=Role.choices)
    preferred_language = models.CharField(
        _("langue preferee"),
        max_length=5,
        choices=LANGUAGE_CHOICES,
        default="fr",
    )
    profile_photo = models.ImageField(upload_to="profiles/", blank=True, null=True)
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


class UserActiveSession(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="active_session",
    )
    session_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-last_seen_at", "-id"]

    def __str__(self):
        return f"{self.user_id}:{self.session_key}"


class EntrepriseInvitation(models.Model):
    email = models.EmailField(db_index=True)
    full_name = models.CharField(max_length=150, blank=True, default="")
    token = models.CharField(max_length=128, unique=True, default=generate_invitation_token)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(default=default_invitation_expiry)
    source = models.CharField(max_length=80, blank=True, default="question_publique", db_index=True)
    last_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    reminder_count = models.PositiveSmallIntegerField(default=0)
    max_reminders = models.PositiveSmallIntegerField(default=2)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["is_used", "expires_at", "created_at"]),
            models.Index(fields=["reminder_count", "last_reminder_sent_at"]),
        ]

    def __str__(self):
        return f"{self.email} ({self.source or 'invitation'})"

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()


class Abonnement(models.Model):
    nom = models.CharField(max_length=50)
    code = models.CharField(max_length=50, blank=True, default="", db_index=True)
    prix = models.FloatField()
    prix_annuel = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    devise = models.CharField(max_length=10, default="USD")
    duree_jours = models.IntegerField()
    actif = models.BooleanField(default=True)
    description = models.TextField(blank=True, default="")
    modules_inclus = models.JSONField(default=list, blank=True)
    max_utilisateurs = models.PositiveIntegerField(null=True, blank=True)
    max_factures_mois = models.PositiveIntegerField(null=True, blank=True)
    max_clients = models.PositiveIntegerField(null=True, blank=True)
    max_apprenants = models.PositiveIntegerField(null=True, blank=True)
    acces_comptabilite = models.BooleanField(default=True)
    acces_exports = models.BooleanField(default=True)

    def __str__(self):
        return self.nom


class AbonnementEntreprise(models.Model):
    class Statut(models.TextChoices):
        ESSAI = "essai", _("Essai")
        ACTIF = "actif", _("Actif")
        EXPIRE = "expire", _("Expire")
        SUSPENDU = "suspendu", _("Suspendu")
        ANNULE = "annule", _("Annule")

    class Renouvellement(models.TextChoices):
        MANUEL = "manuel", _("Manuel")
        MENSUEL = "mensuel", _("Mensuel")
        ANNUEL = "annuel", _("Annuel")

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
    renouvellement = models.CharField(
        max_length=20,
        choices=Renouvellement.choices,
        default=Renouvellement.MANUEL,
    )
    essai = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ["-date_creation", "-id"]

    def __str__(self):
        return f"{self.entreprise.nom} - {self.plan.nom} ({self.statut})"
