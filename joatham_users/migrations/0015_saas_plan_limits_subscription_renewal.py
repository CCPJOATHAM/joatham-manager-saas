from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_users", "0014_entreprise_is_active"),
    ]

    operations = [
        migrations.AlterField(
            model_name="abonnement",
            name="code",
            field=models.CharField(blank=True, db_index=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="abonnement",
            name="acces_comptabilite",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="abonnement",
            name="acces_exports",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="abonnement",
            name="devise",
            field=models.CharField(default="USD", max_length=10),
        ),
        migrations.AddField(
            model_name="abonnement",
            name="max_apprenants",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="abonnement",
            name="max_clients",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="abonnement",
            name="max_factures_mois",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="abonnement",
            name="max_utilisateurs",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="abonnement",
            name="modules_inclus",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="abonnement",
            name="prix_annuel",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="abonnemententreprise",
            name="date_modification",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name="abonnemententreprise",
            name="renouvellement",
            field=models.CharField(
                choices=[("manuel", "Manuel"), ("mensuel", "Mensuel"), ("annuel", "Annuel")],
                default="manuel",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="abonnemententreprise",
            name="statut",
            field=models.CharField(
                choices=[
                    ("essai", "Essai"),
                    ("actif", "Actif"),
                    ("expire", "Expire"),
                    ("suspendu", "Suspendu"),
                    ("annule", "Annule"),
                ],
                default="actif",
                max_length=20,
            ),
        ),
    ]
