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

    def __str__(self):
        return f"{self.description} - {self.montant} FC"
