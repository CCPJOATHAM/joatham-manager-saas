import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("joatham_products", "0003_stockmovement"),
        ("joatham_users", "0020_useractivesession"),
    ]

    operations = [
        migrations.CreateModel(
            name="InventorySession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Brouillon"),
                            ("in_progress", "En cours"),
                            ("closed", "Cloture"),
                            ("validated", "Valide"),
                            ("cancelled", "Annule"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("validated_at", models.DateTimeField(blank=True, null=True)),
                ("comment", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="inventory_sessions_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inventory_sessions",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "validated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="inventory_sessions_validated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="InventoryLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("theoretical_quantity", models.PositiveIntegerField(default=0)),
                ("counted_quantity", models.PositiveIntegerField(blank=True, null=True)),
                ("difference", models.IntegerField(default=0)),
                ("comment", models.TextField(blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inventory_lines",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "produit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inventory_lines",
                        to="joatham_products.produit",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="joatham_products.inventorysession",
                    ),
                ),
            ],
            options={"ordering": ["produit__nom", "id"]},
        ),
        migrations.AddConstraint(
            model_name="inventoryline",
            constraint=models.UniqueConstraint(fields=("session", "produit"), name="uniq_inventory_line_session_product"),
        ),
        migrations.AddConstraint(
            model_name="inventoryline",
            constraint=models.CheckConstraint(condition=models.Q(theoretical_quantity__gte=0), name="inv_line_theoretical_gte_zero"),
        ),
        migrations.AddConstraint(
            model_name="inventoryline",
            constraint=models.CheckConstraint(
                condition=models.Q(counted_quantity__isnull=True) | models.Q(counted_quantity__gte=0),
                name="inv_line_counted_gte_zero_or_null",
            ),
        ),
        migrations.AddIndex(
            model_name="inventorysession",
            index=models.Index(fields=["entreprise", "status"], name="inv_sess_ent_status_idx"),
        ),
        migrations.AddIndex(
            model_name="inventorysession",
            index=models.Index(fields=["entreprise", "started_at"], name="inv_sess_ent_start_idx"),
        ),
        migrations.AddIndex(
            model_name="inventorysession",
            index=models.Index(fields=["entreprise", "validated_at"], name="inv_sess_ent_valid_idx"),
        ),
        migrations.AddIndex(
            model_name="inventoryline",
            index=models.Index(fields=["entreprise", "session"], name="inv_line_ent_session_idx"),
        ),
        migrations.AddIndex(
            model_name="inventoryline",
            index=models.Index(fields=["entreprise", "produit"], name="inv_line_ent_product_idx"),
        ),
        migrations.AddIndex(
            model_name="inventoryline",
            index=models.Index(fields=["session", "produit"], name="inv_line_session_prod_idx"),
        ),
    ]
