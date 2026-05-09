from django.db import models


class Depense(models.Model):
    description = models.CharField(max_length=200)
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)
    entreprise = models.ForeignKey(
        "joatham_users.Entreprise",
        on_delete=models.CASCADE,
        null=True,
        related_name="depenses",
    )
    caisse = models.ForeignKey(
        "joatham_caisse.Caisse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="depenses",
    )
    session_caisse = models.ForeignKey(
        "joatham_caisse.SessionCaisse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="depenses",
    )

    def __str__(self):
        return f"{self.description} - {self.montant} FC"
