from django.db import models
from django.utils.translation import gettext_lazy as _
from joatham_users.models import Abonnement as SaaSPlan
from joatham_users.models import AbonnementEntreprise as SaaSSubscription


class ActivityLog(models.Model):
    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
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
        MENSUEL = "mensuel", _("Mensuel")
        TRIMESTRIEL = "trimestriel", _("Trimestriel")
        SEMESTRIEL = "semestriel", _("Semestriel")
        ANNUEL = "annuel", _("Annuel")

    class Statut(models.TextChoices):
        EN_ATTENTE = "en_attente", _("En attente")
        EN_COURS = "en_cours", _("En cours")
        APPROUVEE = "approuvee", _("Approuvee")
        VALIDE = "valide", _("Valide")
        REFUSE = "refuse", _("Refuse")
        ANNULE = "annule", _("Annule")
        ECHOUE = "echoue", _("Echoue")
        EXPIRE = "expire", _("Expire")

    class Methode(models.TextChoices):
        MANUEL = "manuel", _("Manuel")
        AUTOMATIQUE = "automatique", _("Automatique")
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        CARTE = "carte", _("Carte")
        VIREMENT = "virement", _("Virement")
        CASH = "cash", "Cash"

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
    montant_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    devise_entreprise = models.CharField(max_length=10, default="USD")
    montant_devise_locale_estime = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    taux_change_reference = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    source_taux = models.CharField(max_length=30, default="manuel")
    date_taux = models.DateTimeField(null=True, blank=True)
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE)
    methode_paiement = models.CharField(max_length=30, choices=Methode.choices, default=Methode.MANUEL)
    provider_reference = models.CharField(max_length=120, blank=True, default="")
    provider = models.CharField(max_length=50, blank=True, default="manual", db_index=True)
    provider_checkout_id = models.CharField(max_length=180, blank=True, default="")
    provider_transaction_id = models.CharField(max_length=180, null=True, blank=True, unique=True)
    external_reference = models.CharField(max_length=80, null=True, blank=True, unique=True, db_index=True)
    provider_status = models.CharField(max_length=50, blank=True, default="")
    checkout_url = models.URLField(max_length=500, blank=True, default="")
    amount_expected = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    paid_currency = models.CharField(max_length=10, blank=True, default="")
    raw_provider_payload = models.JSONField(default=dict, blank=True)
    last_webhook_event_id = models.CharField(max_length=180, blank=True, default="", db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True, default="")
    periode_debut = models.DateField(null=True, blank=True)
    periode_fin = models.DateField(null=True, blank=True)
    date_paiement = models.DateTimeField(null=True, blank=True)
    telephone_paiement = models.CharField(max_length=30, blank=True, default="")
    reference_paiement = models.CharField(max_length=120)
    preuve_paiement = models.FileField(upload_to="abonnements/preuves/", blank=True, null=True)
    notes_validation = models.TextField(blank=True, default="")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_validation = models.DateTimeField(null=True, blank=True)
    valide_par = models.ForeignKey(
        "joatham_users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paiements_abonnement_valides",
    )
    created_by = models.ForeignKey(
        "joatham_users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paiements_abonnement_crees",
    )

    class Meta:
        ordering = ["-date_creation", "-id"]
        indexes = [
            models.Index(fields=["entreprise", "statut", "date_creation"]),
            models.Index(fields=["statut", "date_creation"]),
            models.Index(fields=["provider", "statut", "date_creation"]),
        ]

    def __str__(self):
        return f"{self.entreprise.nom} - {self.plan.nom} - {self.get_statut_display()}"


class PlatformSettings(models.Model):
    nom_plateforme = models.CharField(max_length=120, default="JOATHAM Manager")
    email_systeme = models.EmailField(default="admin@joatham.com")
    devise_defaut = models.CharField(max_length=10, default="CDF")
    devise_plateforme = models.CharField(max_length=10, default="USD")
    exchange_rate_provider = models.CharField(max_length=50, default="exchangerate_api")
    exchange_rate_api_key = models.CharField(max_length=255, blank=True, default="")
    exchange_rate_cache_hours = models.PositiveIntegerField(default=12)
    allow_manual_exchange_rate_fallback = models.BooleanField(default=True)
    duree_essai_jours = models.PositiveIntegerField(default=14)
    mode_maintenance = models.BooleanField(default=False)
    message_maintenance = models.TextField(
        blank=True,
        default="Nous effectuons une operation de maintenance afin d'ameliorer votre experience.",
    )
    maintenance_allowed_ips = models.TextField(blank=True, default="")
    maintenance_modules = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Parametres plateforme")
        verbose_name_plural = _("Parametres plateforme")

    def __str__(self):
        return self.nom_plateforme

    @classmethod
    def get_solo(cls):
        settings, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "nom_plateforme": "JOATHAM Manager",
                "email_systeme": "admin@joatham.com",
                "devise_defaut": "CDF",
                "devise_plateforme": "USD",
                "exchange_rate_provider": "exchangerate_api",
                "exchange_rate_api_key": "",
                "exchange_rate_cache_hours": 12,
                "allow_manual_exchange_rate_fallback": True,
                "duree_essai_jours": 14,
                "mode_maintenance": False,
                "message_maintenance": "Nous effectuons une operation de maintenance afin d'ameliorer votre experience.",
                "maintenance_allowed_ips": "",
                "maintenance_modules": [],
            },
        )
        return settings


class ExchangeRate(models.Model):
    devise_source = models.CharField(max_length=10, db_index=True)
    devise_cible = models.CharField(max_length=10, db_index=True)
    taux = models.DecimalField(max_digits=20, decimal_places=8)
    source_provider = models.CharField(max_length=50, default="manuel")
    date_taux = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)
    actif = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-date_taux", "-fetched_at", "-id"]
        indexes = [
            models.Index(fields=["devise_source", "devise_cible", "actif", "date_taux"], name="core_exchan_devise__cb06c8_idx"),
        ]

    def __str__(self):
        return f"{self.devise_source}->{self.devise_cible}: {self.taux}"


class Plan(SaaSPlan):
    class Meta:
        proxy = True
        verbose_name = _("Plan SaaS")
        verbose_name_plural = _("Plans SaaS")


class Abonnement(SaaSSubscription):
    class Meta:
        proxy = True
        verbose_name = _("Abonnement SaaS")
        verbose_name_plural = _("Abonnements SaaS")
