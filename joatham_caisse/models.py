from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from joatham_users.models import Entreprise


class Caisse(models.Model):
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name="caisses")
    nom = models.CharField(max_length=120)
    code = models.CharField(max_length=40)
    description = models.TextField(blank=True, null=True)
    devise = models.CharField(max_length=10, default="CDF")
    est_active = models.BooleanField(default=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="caisses_creees",
        null=True,
        blank=True,
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom", "id"]
        constraints = [
            models.UniqueConstraint(fields=["entreprise", "code"], name="uniq_caisse_code_by_company"),
        ]
        indexes = [
            models.Index(fields=["entreprise", "est_active"], name="cash_company_active_idx"),
            models.Index(fields=["entreprise", "code"], name="cash_company_code_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self.devise and self.entreprise_id:
            self.devise = getattr(self.entreprise, "devise", "") or "CDF"
        self.code = (self.code or "").strip()
        self.nom = (self.nom or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nom} ({self.code})"


class SessionCaisse(models.Model):
    class Statut(models.TextChoices):
        OUVERTE = "ouverte", "Ouverte"
        FERMEE = "fermee", "Fermee"
        VALIDEE = "validee", "Validee"
        ANNULEE = "annulee", "Annulee"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name="sessions_caisse")
    caisse = models.ForeignKey(Caisse, on_delete=models.CASCADE, related_name="sessions")
    utilisateur_ouverture = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sessions_caisse_ouvertes",
    )
    utilisateur_fermeture = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sessions_caisse_fermees",
        null=True,
        blank=True,
    )
    date_ouverture = models.DateTimeField(default=timezone.now)
    date_fermeture = models.DateTimeField(null=True, blank=True)
    solde_initial = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    solde_theorique = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    solde_reel = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ecart = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.OUVERTE)
    commentaire_ouverture = models.TextField(blank=True, default="")
    commentaire_fermeture = models.TextField(blank=True, default="")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_ouverture", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["caisse"],
                condition=Q(statut="ouverte"),
                name="uniq_open_cash_session_per_cashbox",
            ),
            models.CheckConstraint(condition=Q(solde_initial__gte=0), name="cash_session_initial_balance_gte_zero"),
            models.CheckConstraint(
                condition=Q(date_fermeture__isnull=True) | Q(date_fermeture__gte=F("date_ouverture")),
                name="cash_session_close_after_open",
            ),
        ]
        indexes = [
            models.Index(fields=["entreprise", "statut"], name="cash_sess_ent_stat_idx"),
            models.Index(fields=["caisse", "statut"], name="cash_sess_caisse_stat_idx"),
            models.Index(fields=["entreprise", "date_ouverture"], name="cash_session_company_open_idx"),
            models.Index(fields=["entreprise", "date_fermeture"], name="cash_session_company_close_idx"),
        ]

    def __str__(self):
        return f"{self.caisse} - {self.statut}"


class MouvementCaisse(models.Model):
    class TypeMouvement(models.TextChoices):
        ENTREE = "entree", "Entree"
        SORTIE = "sortie", "Sortie"
        DEPENSE = "depense", "Depense"
        PAIEMENT_FACTURE = "paiement_facture", "Paiement facture"
        AJUSTEMENT = "ajustement", "Ajustement"
        TRANSFERT = "transfert", "Transfert"

    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        CONFIRME = "confirme", "Confirme"
        ANNULE = "annule", "Annule"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name="mouvements_caisse")
    caisse = models.ForeignKey(Caisse, on_delete=models.CASCADE, related_name="mouvements")
    session = models.ForeignKey(SessionCaisse, on_delete=models.CASCADE, related_name="mouvements")
    type_mouvement = models.CharField(max_length=30, choices=TypeMouvement.choices)
    montant = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    devise = models.CharField(max_length=10, default="CDF")
    moyen_paiement = models.CharField(max_length=30, blank=True, default="cash", db_index=True)
    libelle = models.CharField(max_length=255)
    reference = models.CharField(max_length=100, blank=True, default="")
    source_app = models.CharField(max_length=50, blank=True, default="")
    source_model = models.CharField(max_length=100, blank=True, default="")
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="mouvements_caisse_crees",
        null=True,
        blank=True,
    )
    date_mouvement = models.DateTimeField(default=timezone.now)
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.CONFIRME)
    commentaire = models.TextField(blank=True, default="")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_mouvement", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(montant__gt=0), name="cash_movement_amount_gt_zero"),
        ]
        indexes = [
            models.Index(fields=["entreprise", "date_mouvement"], name="cash_move_company_date_idx"),
            models.Index(fields=["session", "date_mouvement"], name="cash_move_session_date_idx"),
            models.Index(fields=["caisse", "date_mouvement"], name="cash_move_cashbox_date_idx"),
            models.Index(fields=["entreprise", "type_mouvement", "date_mouvement"], name="cash_mov_ent_type_dt_idx"),
            models.Index(fields=["entreprise", "moyen_paiement", "date_mouvement"], name="cash_mov_ent_method_dt_idx"),
            models.Index(fields=["source_app", "source_model", "source_id"], name="cash_move_source_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self.devise and self.caisse_id:
            self.devise = getattr(self.caisse, "devise", "") or "CDF"
        self.libelle = (self.libelle or "").strip()
        self.reference = (self.reference or "").strip()
        self.moyen_paiement = (self.moyen_paiement or "cash").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.type_mouvement} - {self.montant}"


class ValidationCaisse(models.Model):
    class Decision(models.TextChoices):
        VALIDEE = "validee", "Validee"
        REJETEE = "rejetee", "Rejetee"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name="validations_caisse")
    session = models.ForeignKey(SessionCaisse, on_delete=models.CASCADE, related_name="validations")
    validee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="validations_caisse_effectuees",
    )
    date_validation = models.DateTimeField(default=timezone.now)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    commentaire = models.TextField(blank=True, default="")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_validation", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["session"], name="uniq_cash_validation_per_session"),
        ]
        indexes = [
            models.Index(fields=["entreprise", "date_validation"], name="cash_val_ent_dt_idx"),
            models.Index(fields=["session", "decision"], name="cash_val_sess_dec_idx"),
        ]

    def __str__(self):
        return f"{self.session_id} - {self.decision}"

