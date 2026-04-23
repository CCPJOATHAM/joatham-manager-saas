from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

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


class Facture(models.Model):
    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        EMISE = "emise", "Emise"
        PAYEE = "payee", "Payee"
        ANNULEE = "annulee", "Annulee"

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
        return self.client.nom if self.client else (self.client_nom or "Client non renseigne")

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
            raise ValueError(f"Transition invalide : {self.statut} -> {nouveau_statut}")

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
                self.changer_statut(self.Statut.PAYEE, user=user, note="Paiement complet enregistre.")
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
        ESPECES = "especes", "Especes"
        VIREMENT = "virement", "Virement"
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        CHEQUE = "cheque", "Cheque"
        AUTRE = "autre", "Autre"

    class StatutPaiement(models.TextChoices):
        EN_ATTENTE = "en_attente", "En attente"
        VALIDE = "valide", "Valide"
        ANNULE = "annule", "Annule"

    facture = models.ForeignKey("Facture", on_delete=models.CASCADE, related_name="paiements")
    entreprise = models.ForeignKey("joatham_users.Entreprise", on_delete=models.CASCADE, related_name="paiements_factures")
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
        self.facture.log_action(
            action=FactureHistorique.Action.PAIEMENT,
            description=("Paiement ajoute" if is_create else "Paiement modifie") + f" : {self.montant} via {self.mode}.",
        )
        self.facture.actualiser_statut_depuis_paiements()


class FactureHistorique(models.Model):
    class Action(models.TextChoices):
        CREATION = "creation", "Creation"
        MODIFICATION = "modification", "Modification"
        STATUT = "statut", "Changement de statut"
        PAIEMENT = "paiement", "Paiement"
        PDF = "pdf", "Generation PDF"

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
