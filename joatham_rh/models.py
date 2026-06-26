from django.conf import settings
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class Poste(models.Model):
    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="rh_postes",
    )
    nom = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom", "id"]
        constraints = [
            models.UniqueConstraint(fields=["entreprise", "nom"], name="rh_unique_poste_nom_per_entreprise"),
        ]
        indexes = [
            models.Index(fields=["entreprise", "actif"], name="rh_poste_ent_actif_idx"),
            models.Index(fields=["entreprise", "nom"], name="rh_poste_ent_nom_idx"),
        ]

    def save(self, *args, **kwargs):
        self.nom = (self.nom or "").strip()
        self.description = (self.description or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom


class Employe(models.Model):
    class Sexe(models.TextChoices):
        HOMME = "homme", "Homme"
        FEMME = "femme", "Femme"
        AUTRE = "autre", "Autre"

    class TypeContrat(models.TextChoices):
        CDI = "cdi", "CDI"
        CDD = "cdd", "CDD"
        STAGE = "stage", "Stage"
        JOURNALIER = "journalier", "Journalier"
        PRESTATION = "prestation", "Prestation"
        AUTRE = "autre", "Autre"

    class Statut(models.TextChoices):
        ACTIF = "actif", "Actif"
        SUSPENDU = "suspendu", "Suspendu"
        SORTI = "sorti", "Sorti"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="rh_employes",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rh_employe",
        verbose_name="Compte utilisateur lie",
    )
    matricule = models.CharField(max_length=50)
    nom = models.CharField(max_length=120)
    prenom = models.CharField(max_length=120)
    sexe = models.CharField(max_length=20, choices=Sexe.choices, blank=True, default="")
    telephone = models.CharField(max_length=50, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    adresse = models.CharField(max_length=255, blank=True, default="")
    poste = models.ForeignKey(
        Poste,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employes",
    )
    type_contrat = models.CharField(max_length=20, choices=TypeContrat.choices, default=TypeContrat.CDI)
    date_embauche = models.DateField()
    salaire_base = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.ACTIF)
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom", "prenom", "id"]
        constraints = [
            models.UniqueConstraint(fields=["entreprise", "matricule"], name="rh_unique_matricule_per_entreprise"),
            models.CheckConstraint(
                condition=Q(salaire_base__isnull=True) | Q(salaire_base__gte=0),
                name="rh_employe_salaire_base_gte_zero",
            ),
        ]
        indexes = [
            models.Index(fields=["entreprise", "statut"], name="rh_emp_ent_statut_idx"),
            models.Index(fields=["entreprise", "actif"], name="rh_emp_ent_actif_idx"),
            models.Index(fields=["entreprise", "matricule"], name="rh_emp_ent_matricule_idx"),
        ]

    def save(self, *args, **kwargs):
        self.matricule = (self.matricule or "").strip()
        self.nom = (self.nom or "").strip()
        self.prenom = (self.prenom or "").strip()
        self.telephone = (self.telephone or "").strip()
        self.adresse = (self.adresse or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.matricule} - {self.nom} {self.prenom}".strip()


class Presence(models.Model):
    class Statut(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        RETARD = "retard", "Retard"
        CONGE = "conge", "Conge"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="rh_presences",
    )
    employe = models.ForeignKey(
        Employe,
        on_delete=models.CASCADE,
        related_name="presences",
    )
    date = models.DateField()
    statut = models.CharField(max_length=20, choices=Statut.choices)
    heure_arrivee = models.TimeField(null=True, blank=True)
    heure_depart = models.TimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "employe__nom", "id"]
        constraints = [
            models.UniqueConstraint(fields=["employe", "date"], name="rh_unique_presence_employe_date"),
        ]
        indexes = [
            models.Index(fields=["entreprise", "date"], name="rh_presence_ent_date_idx"),
            models.Index(fields=["entreprise", "statut", "date"], name="rh_presence_ent_statut_dt_idx"),
            models.Index(fields=["employe", "date"], name="rh_presence_emp_date_idx"),
        ]

    def save(self, *args, **kwargs):
        self.note = (self.note or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employe} - {self.date} - {self.statut}"


class DemandeConge(models.Model):
    class TypeConge(models.TextChoices):
        ANNUEL = "annuel", "Annuel"
        MALADIE = "maladie", "Maladie"
        EXCEPTIONNEL = "exceptionnel", "Exceptionnel"
        SANS_SOLDE = "sans_solde", "Sans solde"
        AUTRE = "autre", "Autre"

    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        EN_ATTENTE = "en_attente", "En attente"
        APPROUVE = "approuve", "Approuve"
        REFUSE = "refuse", "Refuse"
        ANNULE = "annule", "Annule"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="rh_conges",
    )
    employe = models.ForeignKey(
        Employe,
        on_delete=models.CASCADE,
        related_name="conges",
    )
    type_conge = models.CharField(max_length=20, choices=TypeConge.choices)
    date_debut = models.DateField()
    date_fin = models.DateField()
    motif = models.TextField(blank=True, default="")
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE)
    approuve_par = models.ForeignKey(
        "joatham_users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rh_conges_decides",
    )
    date_decision = models.DateTimeField(null=True, blank=True)
    commentaire_decision = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_debut", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(date_fin__gte=F("date_debut")), name="rh_conge_date_fin_gte_debut"),
        ]
        indexes = [
            models.Index(fields=["entreprise", "statut", "date_debut"], name="rh_conge_ent_statut_dt_idx"),
            models.Index(fields=["entreprise", "date_debut"], name="rh_conge_ent_debut_idx"),
            models.Index(fields=["employe", "date_debut"], name="rh_conge_emp_debut_idx"),
        ]

    def save(self, *args, **kwargs):
        self.motif = (self.motif or "").strip()
        self.commentaire_decision = (self.commentaire_decision or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employe} - {self.type_conge} - {self.date_debut}"


class DocumentRH(models.Model):
    class TypeDocument(models.TextChoices):
        CONTRAT = "contrat", "Contrat"
        PIECE_IDENTITE = "piece_identite", "Piece d'identite"
        ATTESTATION = "attestation", "Attestation"
        CERTIFICAT = "certificat", "Certificat"
        AUTRE = "autre", "Autre"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="rh_documents",
    )
    employe = models.ForeignKey(
        Employe,
        on_delete=models.CASCADE,
        related_name="documents_rh",
    )
    type_document = models.CharField(max_length=30, choices=TypeDocument.choices)
    titre = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    date_document = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["entreprise", "type_document"], name="rh_doc_ent_type_idx"),
            models.Index(fields=["entreprise", "created_at"], name="rh_doc_ent_created_idx"),
            models.Index(fields=["employe", "created_at"], name="rh_doc_emp_created_idx"),
        ]

    def save(self, *args, **kwargs):
        self.titre = (self.titre or "").strip()
        self.description = (self.description or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.titre

class AvanceSalaire(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = "en_attente", "En attente"
        VALIDEE = "validee", "Validée"
        ANNULEE = "annulee", "Annulée"

    class ModePaiement(models.TextChoices):
        ESPECES = "especes", "Espèces"
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        VIREMENT = "virement", "Virement"
        AUTRE = "autre", "Autre"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="rh_avances_salaire",
    )
    employe = models.ForeignKey(
        Employe,
        on_delete=models.CASCADE,
        related_name="avances_salaire",
    )
    date_avance = models.DateField(default=timezone.localdate)
    montant = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    motif = models.TextField(blank=True, default="")
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.VALIDEE)
    mode_paiement = models.CharField(max_length=20, choices=ModePaiement.choices, default=ModePaiement.ESPECES)
    reference = models.CharField(max_length=100, blank=True, default="")
    cree_par = models.ForeignKey(
        "joatham_users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rh_avances_salaire_creees",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_avance", "-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(montant__gt=0), name="rh_avance_salaire_montant_gt_zero"),
        ]
        indexes = [
            models.Index(fields=["entreprise", "date_avance"], name="rh_avance_ent_date_idx"),
            models.Index(fields=["entreprise", "statut", "date_avance"], name="rh_avance_ent_statut_dt_idx"),
            models.Index(fields=["employe", "date_avance"], name="rh_avance_emp_date_idx"),
        ]

    def save(self, *args, **kwargs):
        self.motif = (self.motif or "").strip()
        self.reference = (self.reference or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employe} - {self.montant} - {self.date_avance}"


class PaiementSalaire(models.Model):
    class Statut(models.TextChoices):
        NON_PAYE = "non_paye", "Non payé"
        PARTIEL = "partiel", "Partiel"
        PAYE = "paye", "Payé"

    class ModePaiement(models.TextChoices):
        ESPECES = "especes", "Espèces"
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        VIREMENT = "virement", "Virement"
        AUTRE = "autre", "Autre"

    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        related_name="rh_paiements_salaire",
    )
    employe = models.ForeignKey(
        Employe,
        on_delete=models.CASCADE,
        related_name="paiements_salaire",
    )
    periode_mois = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    periode_annee = models.PositiveSmallIntegerField(validators=[MinValueValidator(2000)])
    salaire_base = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True, validators=[MinValueValidator(0)])
    total_avances_deduites = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    primes = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True, validators=[MinValueValidator(0)])
    retenues = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True, validators=[MinValueValidator(0)])
    montant_net_a_payer = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    montant_paye = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True, validators=[MinValueValidator(0)])
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.NON_PAYE)
    date_paiement = models.DateField(null=True, blank=True)
    mode_paiement = models.CharField(max_length=20, choices=ModePaiement.choices, default=ModePaiement.ESPECES)
    reference = models.CharField(max_length=100, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    cree_par = models.ForeignKey(
        "joatham_users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rh_paiements_salaire_crees",
    )
    caisse = models.ForeignKey(
        "joatham_caisse.Caisse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rh_paiements_salaire",
    )
    session_caisse = models.ForeignKey(
        "joatham_caisse.SessionCaisse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rh_paiements_salaire",
    )
    mouvement_caisse = models.OneToOneField(
        "joatham_caisse.MouvementCaisse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rh_paiement_salaire",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-periode_annee", "-periode_mois", "employe__nom", "-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(periode_mois__gte=1) & Q(periode_mois__lte=12), name="rh_paie_mois_valid"),
            models.CheckConstraint(condition=Q(salaire_base__gte=0), name="rh_paie_salaire_base_gte_zero"),
            models.CheckConstraint(condition=Q(total_avances_deduites__gte=0), name="rh_paie_avances_gte_zero"),
            models.CheckConstraint(condition=Q(primes__gte=0), name="rh_paie_primes_gte_zero"),
            models.CheckConstraint(condition=Q(retenues__gte=0), name="rh_paie_retenues_gte_zero"),
            models.CheckConstraint(condition=Q(montant_net_a_payer__gte=0), name="rh_paie_net_gte_zero"),
            models.CheckConstraint(condition=Q(montant_paye__gte=0), name="rh_paie_montant_paye_gte_zero"),
        ]
        indexes = [
            models.Index(fields=["entreprise", "periode_annee", "periode_mois"], name="rh_paie_ent_period_idx"),
            models.Index(fields=["entreprise", "statut"], name="rh_paie_ent_statut_idx"),
            models.Index(fields=["employe", "periode_annee", "periode_mois"], name="rh_paie_emp_period_idx"),
            models.Index(fields=["caisse", "session_caisse"], name="rh_paie_cash_session_idx"),
        ]

    def save(self, *args, **kwargs):
        self.reference = (self.reference or "").strip()
        self.notes = (self.notes or "").strip()
        net = (self.salaire_base or Decimal("0.00")) + (self.primes or Decimal("0.00"))
        net -= (self.retenues or Decimal("0.00")) + (self.total_avances_deduites or Decimal("0.00"))
        self.montant_net_a_payer = max(net, Decimal("0.00"))
        if (self.montant_paye or Decimal("0.00")) <= 0:
            self.statut = self.Statut.NON_PAYE
        elif self.montant_paye < self.montant_net_a_payer:
            self.statut = self.Statut.PARTIEL
        else:
            self.statut = self.Statut.PAYE
        super().save(*args, **kwargs)

    @property
    def reste_a_payer(self):
        return max((self.montant_net_a_payer or Decimal("0.00")) - (self.montant_paye or Decimal("0.00")), Decimal("0.00"))

    def __str__(self):
        return f"{self.employe} - {self.periode_mois:02d}/{self.periode_annee}"
