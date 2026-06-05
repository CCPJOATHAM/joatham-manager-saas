from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("joatham_billing", "0009_alter_paiementfacture_mode"),
        ("joatham_clients", "0001_initial"),
        ("joatham_products", "0004_inventorysession_inventoryline"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProformaSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("dernier_numero", models.PositiveIntegerField(default=0)),
                (
                    "entreprise",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="proforma_sequence",
                        to="joatham_users.entreprise",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Proforma",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("client_nom", models.CharField(blank=True, max_length=100, null=True)),
                ("numero", models.CharField(editable=False, max_length=24)),
                ("numero_sequence", models.PositiveIntegerField(editable=False)),
                ("tva", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("remise", models.FloatField(default=0)),
                ("rabais", models.FloatField(default=0)),
                ("ristourne", models.FloatField(default=0)),
                ("montant", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("brouillon", "Brouillon"),
                            ("envoyee", "Envoyee"),
                            ("acceptee", "Acceptee"),
                            ("annulee", "Annulee"),
                            ("convertie", "Convertie"),
                        ],
                        default="brouillon",
                        max_length=20,
                    ),
                ),
                ("date", models.DateTimeField(auto_now_add=True)),
                ("date_validite", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True, default="")),
                ("conditions", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "client",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="joatham_clients.client",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="proformas_creees",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="proformas",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "facture_convertie",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="proforma_source",
                        to="joatham_billing.facture",
                    ),
                ),
            ],
            options={
                "ordering": ["-date", "-id"],
            },
        ),
        migrations.CreateModel(
            name="LigneProforma",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("designation", models.CharField(max_length=200)),
                ("quantite", models.IntegerField(default=1)),
                ("prix_unitaire", models.DecimalField(decimal_places=2, max_digits=10)),
                ("tva", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                (
                    "produit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lignes_proforma",
                        to="joatham_products.produit",
                    ),
                ),
                (
                    "proforma",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lignes",
                        to="joatham_billing.proforma",
                    ),
                ),
                (
                    "service",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lignes_proforma",
                        to="joatham_billing.service",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="proforma",
            constraint=models.UniqueConstraint(fields=("entreprise", "numero"), name="uniq_proforma_numero_par_entreprise"),
        ),
        migrations.AddConstraint(
            model_name="proforma",
            constraint=models.UniqueConstraint(
                fields=("entreprise", "numero_sequence"),
                name="uniq_proforma_sequence_par_entreprise",
            ),
        ),
    ]
