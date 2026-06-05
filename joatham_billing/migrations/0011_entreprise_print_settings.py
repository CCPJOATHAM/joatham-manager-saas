from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_users", "0020_useractivesession"),
        ("joatham_billing", "0010_proforma_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="EntreprisePrintSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pos_width", models.CharField(choices=[("80", "80 mm"), ("58", "58 mm")], default="80", max_length=2)),
                ("pos_show_logo", models.BooleanField(default=True)),
                ("pos_show_company_name", models.BooleanField(default=True)),
                ("pos_show_address", models.BooleanField(default=True)),
                ("pos_show_phone", models.BooleanField(default=True)),
                ("pos_show_email", models.BooleanField(default=True)),
                ("pos_show_tax_info", models.BooleanField(default=True)),
                ("pos_show_generated_by", models.BooleanField(default=True)),
                ("default_invoice_format", models.CharField(choices=[("a4", "A4"), ("pos", "POS / ticket")], default="a4", max_length=3)),
                ("pos_footer_message", models.CharField(blank=True, default="Merci pour votre confiance", max_length=180)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "entreprise",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="print_settings",
                        to="joatham_users.entreprise",
                    ),
                ),
            ],
            options={
                "verbose_name": "Parametres impression entreprise",
                "verbose_name_plural": "Parametres impression entreprise",
            },
        ),
    ]
