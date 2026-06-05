from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from joatham_clients.models import Client


class FactureSequence(models.Model):
    entreprise = models.OneToOneField(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="facture_sequence",
    )
    dernier_numero = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Sequence {self.entreprise.nom} ({self.dernier_numero})"


class ProformaSequence(models.Model):
    entreprise = models.OneToOneField(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="proforma_sequence",
    )
    dernier_numero = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Sequence proforma {self.entreprise.nom} ({self.dernier_numero})"


class Facture(models.Model):
    class Statut(models.TextChoices):
        BROUILLON = "brouillon", _("Brouillon")
        EMISE = "emise", _("Emise")
        PAYEE = "payee", _("Payee")
        ANNULEE = "annulee", _("Annulee")

    client = models.ForeignKey(Client, on_delete=models.CASCADE, null=True, blank=True)
    client_nom = models.CharField(max_length=100, blank=True, null=True)

    numero = models.CharField(max_length=20, editable=False)
    numero_sequence = models.PositiveIntegerField(editable=False)

    montant = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description = models.TextField(blank=True, default="")
    tva = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="factures",
    )

    remise = models.FloatField(default=0)
    rabais = models.FloatField(default=0)
    ristourne = models.FloatField(default=0)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.BROUILLON,
    )

    date = models.DateTimeField(auto_now_add=True)
    paye = models.BooleanField(default=False)
    stock_applique = models.BooleanField(default=False)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["entreprise", "numero"],
                name="uniq_facture_numero_par_entreprise",
            ),
            models.UniqueConstraint(
                fields=["entreprise", "numero_sequence"],
                name="uniq_facture_sequence_par_entreprise",
            ),
        ]

    def __str__(self):
        return self.numero or f"Facture {self.pk}"

    @property
    def client_display(self):
        return self.client.nom if self.client else (self.client_nom or _("Client non renseigne"))

    @property
    def total_ht(self):
        if self.pk:
            lignes = self._prefetched_objects_cache.get("lignes") if hasattr(self, "_prefetched_objects_cache") else None
            if lignes is None:
                lignes = self.lignes.all()
            return sum((ligne.montant for ligne in lignes), Decimal("0"))
        return Decimal(self.montant or 0)

    @property
    def total_tva(self):
        return self.total_ht * Decimal(self.tva or 0) / Decimal("100")

    @property
    def total_reduction(self):
        total_ht = self.total_ht
        remise = total_ht * Decimal(str(self.remise or 0)) / Decimal("100")
        rabais = total_ht * Decimal(str(self.rabais or 0)) / Decimal("100")
        ristourne = total_ht * Decimal(str(self.ristourne or 0)) / Decimal("100")
        return remise + rabais + ristourne

    @property
    def total_net(self):
        return self.total_ht + self.total_tva - self.total_reduction

    @property
    def total_paye(self):
        if not self.pk:
            return Decimal("0")
        paiements = self._prefetched_objects_cache.get("paiements") if hasattr(self, "_prefetched_objects_cache") else None
        if paiements is None:
            paiements = self.paiements.all()
        return sum(
            (paiement.montant for paiement in paiements if paiement.statut == PaiementFacture.StatutPaiement.VALIDE),
            Decimal("0"),
        )

    @property
    def reste_a_payer(self):
        reste = self.total_net - self.total_paye
        return reste if reste > Decimal("0") else Decimal("0")

    @property
    def est_partiellement_payee(self):
        return self.total_paye > Decimal("0") and self.reste_a_payer > Decimal("0")

    def peut_passer_a(self, nouveau_statut):
        transitions = {
            self.Statut.BROUILLON: {self.Statut.EMISE, self.Statut.ANNULEE},
            self.Statut.EMISE: {self.Statut.PAYEE, self.Statut.ANNULEE},
            self.Statut.PAYEE: set(),
            self.Statut.ANNULEE: set(),
        }
        return nouveau_statut == self.statut or nouveau_statut in transitions.get(self.statut, set())

    def changer_statut(self, nouveau_statut, user=None, note=""):
        if not self.peut_passer_a(nouveau_statut):
            raise ValueError(_("Transition invalide : %(old)s -> %(new)s") % {"old": self.statut, "new": nouveau_statut})

        ancien_statut = self.statut
        self.statut = nouveau_statut
        self.paye = nouveau_statut == self.Statut.PAYEE
        self.save(update_fields=["statut", "paye"])
        self.log_action(
            action=FactureHistorique.Action.STATUT,
            user=user,
            description=f"Statut change de {ancien_statut} vers {nouveau_statut}. {note}".strip(),
        )

    def actualiser_statut_depuis_paiements(self, user=None):
        if self.statut == self.Statut.ANNULEE:
            return
        if self.reste_a_payer == Decimal("0") and self.total_paye > Decimal("0"):
            if self.statut != self.Statut.PAYEE:
                self.changer_statut(self.Statut.PAYEE, user=user, note=_("Paiement complet enregistre."))
        else:
            paye = False
            if self.paye != paye:
                self.paye = paye
                self.save(update_fields=["paye"])

    def log_action(self, action, user=None, description="", metadata=None):
        FactureHistorique.objects.create(
            facture=self,
            entreprise=self.entreprise,
            user=user,
            action=action,
            description=description,
            metadata=metadata or {},
        )

    def assign_numero(self):
        if self.numero and self.numero_sequence:
            return

        with transaction.atomic():
            sequence, _ = FactureSequence.objects.select_for_update().get_or_create(
                entreprise=self.entreprise
            )
            sequence.dernier_numero += 1
            sequence.save(update_fields=["dernier_numero"])

            self.numero_sequence = sequence.dernier_numero
            number_format = getattr(settings, "JOATHAM_FACTURE_NUMBER_FORMAT", "standard")
            if number_format == "yearly":
                year = timezone.now().year
                self.numero = f"F-{year}-{sequence.dernier_numero:04d}"
            else:
                self.numero = f"F-{sequence.dernier_numero:04d}"

    def save(self, *args, **kwargs):
        if not self.numero:
            self.assign_numero()
        super().save(*args, **kwargs)


class Proforma(models.Model):
    class Statut(models.TextChoices):
        BROUILLON = "brouillon", _("Brouillon")
        ENVOYEE = "envoyee", _("Envoyee")
        ACCEPTEE = "acceptee", _("Acceptee")
        ANNULEE = "annulee", _("Annulee")
        CONVERTIE = "convertie", _("Convertie")

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="proformas",
    )
    client = models.ForeignKey(Client, on_delete=models.CASCADE, null=True, blank=True)
    client_nom = models.CharField(max_length=100, blank=True, null=True)
    numero = models.CharField(max_length=24, editable=False)
    numero_sequence = models.PositiveIntegerField(editable=False)
    tva = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    remise = models.FloatField(default=0)
    rabais = models.FloatField(default=0)
    ristourne = models.FloatField(default=0)
    montant = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.BROUILLON)
    date = models.DateTimeField(auto_now_add=True)
    date_validite = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    conditions = models.TextField(blank=True, default="")
    facture_convertie = models.OneToOneField(
        "Facture",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proforma_source",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proformas_creees",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["entreprise", "numero"],
                name="uniq_proforma_numero_par_entreprise",
            ),
            models.UniqueConstraint(
                fields=["entreprise", "numero_sequence"],
                name="uniq_proforma_sequence_par_entreprise",
            ),
        ]

    def __str__(self):
        return self.numero or f"Proforma {self.pk}"

    @property
    def client_display(self):
        return self.client.nom if self.client else (self.client_nom or _("Client non renseigne"))

    @property
    def total_ht(self):
        if self.pk:
            lignes = self._prefetched_objects_cache.get("lignes") if hasattr(self, "_prefetched_objects_cache") else None
            if lignes is None:
                lignes = self.lignes.all()
            return sum((ligne.montant for ligne in lignes), Decimal("0"))
        return Decimal(self.montant or 0)

    @property
    def total_tva(self):
        return self.total_ht * Decimal(self.tva or 0) / Decimal("100")

    @property
    def total_reduction(self):
        total_ht = self.total_ht
        remise = total_ht * Decimal(str(self.remise or 0)) / Decimal("100")
        rabais = total_ht * Decimal(str(self.rabais or 0)) / Decimal("100")
        ristourne = total_ht * Decimal(str(self.ristourne or 0)) / Decimal("100")
        return remise + rabais + ristourne

    @property
    def total_net(self):
        return self.total_ht + self.total_tva - self.total_reduction

    def assign_numero(self):
        if self.numero and self.numero_sequence:
            return

        with transaction.atomic():
            sequence, _ = ProformaSequence.objects.select_for_update().get_or_create(
                entreprise=self.entreprise
            )
            sequence.dernier_numero += 1
            sequence.save(update_fields=["dernier_numero"])

            self.numero_sequence = sequence.dernier_numero
            number_format = getattr(settings, "JOATHAM_PROFORMA_NUMBER_FORMAT", "standard")
            if number_format == "yearly":
                year = timezone.now().year
                self.numero = f"PF-{year}-{sequence.dernier_numero:04d}"
            else:
                self.numero = f"PF-{sequence.dernier_numero:04d}"

    def save(self, *args, **kwargs):
        if not self.numero:
            self.assign_numero()
        super().save(*args, **kwargs)


class EntreprisePrintSettings(models.Model):
    class POSWidth(models.TextChoices):
        WIDTH_80 = "80", "80 mm"
        WIDTH_58 = "58", "58 mm"

    class InvoiceFormat(models.TextChoices):
        A4 = "a4", _("A4")
        POS = "pos", _("POS / ticket")

    entreprise = models.OneToOneField(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="print_settings",
    )
    pos_width = models.CharField(max_length=2, choices=POSWidth.choices, default=POSWidth.WIDTH_80)
    pos_show_logo = models.BooleanField(default=True)
    pos_show_company_name = models.BooleanField(default=True)
    pos_show_address = models.BooleanField(default=True)
    pos_show_phone = models.BooleanField(default=True)
    pos_show_email = models.BooleanField(default=True)
    pos_show_tax_info = models.BooleanField(default=True)
    pos_show_generated_by = models.BooleanField(default=True)
    default_invoice_format = models.CharField(max_length=3, choices=InvoiceFormat.choices, default=InvoiceFormat.A4)
    pos_footer_message = models.CharField(max_length=180, default="Merci pour votre confiance", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Parametres impression entreprise")
        verbose_name_plural = _("Parametres impression entreprise")

    def __str__(self):
        return f"Parametres impression - {self.entreprise}"

    @property
    def pos_page_width_css(self):
        return "58mm" if self.pos_width == self.POSWidth.WIDTH_58 else "80mm"

    @property
    def pos_content_width_css(self):
        return "50mm" if self.pos_width == self.POSWidth.WIDTH_58 else "72mm"

    @property
    def pos_margin_css(self):
        return "4mm"


class LigneProforma(models.Model):
    proforma = models.ForeignKey("Proforma", on_delete=models.CASCADE, related_name="lignes")
    produit = models.ForeignKey(
        "joatham_products.Produit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lignes_proforma",
    )
    service = models.ForeignKey(
        "Service",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lignes_proforma",
    )
    designation = models.CharField(max_length=200)
    quantite = models.IntegerField(default=1)
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2)
    tva = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    @property
    def montant(self):
        return Decimal(self.quantite) * Decimal(self.prix_unitaire)

    def __str__(self):
        return f"{self.designation} x{self.quantite}"


class LigneFacture(models.Model):
    facture = models.ForeignKey("Facture", on_delete=models.CASCADE, related_name="lignes")
    produit = models.ForeignKey(
        "joatham_products.Produit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lignes_facture",
    )
    service = models.ForeignKey(
        "Service",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lignes_facture",
    )
    designation = models.CharField(max_length=200)
    quantite = models.IntegerField(default=1)
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2)
    tva = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    @property
    def montant(self):
        return Decimal(self.quantite) * Decimal(self.prix_unitaire)

    def __str__(self):
        return f"{self.designation} x{self.quantite}"


class Service(models.Model):
    nom = models.CharField(max_length=100)
    prix = models.DecimalField(max_digits=10, decimal_places=2)
    actif = models.BooleanField(default=True)
    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        null=True,
    )
    numero = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"{self.nom} - {self.prix}"


class PaiementFacture(models.Model):
    class ModePaiement(models.TextChoices):
        ESPECES = "especes", _("Especes")
        VIREMENT = "virement", _("Virement")
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        MPESA = "mpesa", "M-Pesa"
        ORANGE_MONEY = "orange_money", "Orange Money"
        AIRTEL_MONEY = "airtel_money", "Airtel Money"
        AFRIMONEY = "afrimoney", "Afrimoney"
        CARTE = "carte", _("Carte bancaire")
        CHEQUE = "cheque", _("Cheque")
        AUTRE = "autre", _("Autre")

    class StatutPaiement(models.TextChoices):
        EN_ATTENTE = "en_attente", _("En attente")
        VALIDE = "valide", _("Valide")
        ANNULE = "annule", _("Annule")

    facture = models.ForeignKey("Facture", on_delete=models.CASCADE, related_name="paiements")
    entreprise = models.ForeignKey("joatham_users.Entreprise", on_delete=models.CASCADE, related_name="paiements_factures")
    caisse = models.ForeignKey(
        "joatham_caisse.Caisse",
        on_delete=models.SET_NULL,
        related_name="paiements_factures",
        null=True,
        blank=True,
    )
    session_caisse = models.ForeignKey(
        "joatham_caisse.SessionCaisse",
        on_delete=models.SET_NULL,
        related_name="paiements_factures",
        null=True,
        blank=True,
    )
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    mode = models.CharField(max_length=20, choices=ModePaiement.choices, default=ModePaiement.ESPECES)
    reference = models.CharField(max_length=100, blank=True, default="")
    date_paiement = models.DateTimeField(default=timezone.now)
    statut = models.CharField(max_length=20, choices=StatutPaiement.choices, default=StatutPaiement.VALIDE)
    note = models.TextField(blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_paiement", "-id"]

    def __str__(self):
        return f"Paiement {self.facture.numero} - {self.montant}"

    def save(self, *args, **kwargs):
        self.entreprise = self.facture.entreprise
        is_create = self.pk is None
        super().save(*args, **kwargs)
        action_label = _("Paiement ajoute") if is_create else _("Paiement modifie")
        self.facture.log_action(
            action=FactureHistorique.Action.PAIEMENT,
            description=_("%(action)s : %(amount)s via %(mode)s.")
            % {"action": action_label, "amount": self.montant, "mode": self.mode},
        )
        self.facture.actualiser_statut_depuis_paiements()


class FactureHistorique(models.Model):
    class Action(models.TextChoices):
        CREATION = "creation", _("Creation")
        MODIFICATION = "modification", _("Modification")
        STATUT = "statut", _("Changement de statut")
        PAIEMENT = "paiement", _("Paiement")
        PDF = "pdf", _("Generation PDF")

    facture = models.ForeignKey("Facture", on_delete=models.CASCADE, related_name="historique")
    entreprise = models.ForeignKey("joatham_users.Entreprise", on_delete=models.CASCADE, related_name="historique_factures")
    user = models.ForeignKey(
        "joatham_users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actions_factures",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    description = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.facture.numero} - {self.action}"
