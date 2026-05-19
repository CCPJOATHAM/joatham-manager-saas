from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


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
