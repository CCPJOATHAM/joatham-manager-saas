from django.db import models

class Client(models.Model):
    nom = models.CharField(max_length=100)
    telephone = models.CharField(max_length=20)
    email = models.EmailField()

    entreprise = models.ForeignKey(
        'joatham_users.Entreprise',
        on_delete=models.CASCADE,
        null=True
    )

    def __str__(self):
        return self.nom