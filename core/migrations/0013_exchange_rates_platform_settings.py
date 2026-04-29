from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_paiementabonnement_plan_request_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="paiementabonnement",
            name="date_taux",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="allow_manual_exchange_rate_fallback",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="devise_plateforme",
            field=models.CharField(default="USD", max_length=10),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="exchange_rate_api_key",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="exchange_rate_cache_hours",
            field=models.PositiveIntegerField(default=12),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="exchange_rate_provider",
            field=models.CharField(default="exchangerate_api", max_length=50),
        ),
        migrations.CreateModel(
            name="ExchangeRate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("devise_source", models.CharField(db_index=True, max_length=10)),
                ("devise_cible", models.CharField(db_index=True, max_length=10)),
                ("taux", models.DecimalField(decimal_places=8, max_digits=20)),
                ("source_provider", models.CharField(default="manuel", max_length=50)),
                ("date_taux", models.DateTimeField()),
                ("fetched_at", models.DateTimeField(auto_now_add=True)),
                ("actif", models.BooleanField(default=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "ordering": ["-date_taux", "-fetched_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="exchangerate",
            index=models.Index(fields=["devise_source", "devise_cible", "actif", "date_taux"], name="core_exchan_devise__e3cf1a_idx"),
        ),
    ]
