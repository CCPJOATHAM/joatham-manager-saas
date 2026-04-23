from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("joatham_users", "0006_subscription_v1"),
    ]

    operations = [
        migrations.CreateModel(
            name="Produit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=150)),
                ("reference", models.CharField(blank=True, default="", max_length=80)),
                ("prix_unitaire", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("quantite_stock", models.PositiveIntegerField(default=0)),
                ("seuil_alerte", models.PositiveIntegerField(default=0)),
                ("actif", models.BooleanField(default=True)),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                (
                    "entreprise",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="produits", to="joatham_users.entreprise"),
                ),
            ],
            options={"ordering": ["nom", "id"]},
        ),
        migrations.AddConstraint(
            model_name="produit",
            constraint=models.UniqueConstraint(
                fields=("entreprise", "reference"),
                name="unique_product_reference_per_entreprise",
            ),
        ),
    ]
