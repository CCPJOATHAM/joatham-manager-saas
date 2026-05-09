import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("joatham_products", "0002_produit_description"),
        ("joatham_users", "0020_useractivesession"),
    ]

    operations = [
        migrations.CreateModel(
            name="StockMovement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "movement_type",
                    models.CharField(
                        choices=[
                            ("manual_entry", "Entree manuelle"),
                            ("manual_exit", "Sortie manuelle"),
                            ("invoice_sale", "Vente facture"),
                            ("invoice_restore", "Restauration facture"),
                            ("adjustment_positive", "Ajustement positif"),
                            ("adjustment_negative", "Ajustement negatif"),
                            ("inventory_recount", "Inventaire"),
                            ("transfer_out", "Transfert sortant"),
                            ("transfer_in", "Transfert entrant"),
                        ],
                        max_length=30,
                    ),
                ),
                ("quantity", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("stock_before", models.PositiveIntegerField(default=0)),
                ("stock_after", models.PositiveIntegerField(default=0)),
                ("unit_cost", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("reference", models.CharField(blank=True, default="", max_length=120)),
                ("reason", models.CharField(blank=True, default="", max_length=120)),
                ("comment", models.TextField(blank=True, default="")),
                ("source_app", models.CharField(blank=True, default="", max_length=50)),
                ("source_model", models.CharField(blank=True, default="", max_length=100)),
                ("source_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stock_movements_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stock_movements",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "produit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stock_movements",
                        to="joatham_products.produit",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="stock_mov_qty_gt_zero"),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(condition=models.Q(stock_before__gte=0), name="stock_mov_before_gte_zero"),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(condition=models.Q(stock_after__gte=0), name="stock_mov_after_gte_zero"),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["entreprise", "created_at"], name="stock_mov_ent_created_idx"),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["entreprise", "movement_type", "created_at"], name="stock_mov_ent_type_dt_idx"),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["produit", "created_at"], name="stock_mov_prod_date_idx"),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["source_app", "source_model", "source_id"], name="stock_mov_source_idx"),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["entreprise", "produit", "created_at"], name="stock_mov_ent_prod_dt_idx"),
        ),
    ]
