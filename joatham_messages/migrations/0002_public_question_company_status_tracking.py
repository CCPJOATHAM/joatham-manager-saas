from django.db import migrations, models
from django.utils import timezone


def normalize_request_statuses(apps, schema_editor):
    final_status_date = timezone.now()
    for model_name in ("SuggestionSuperAdmin", "PublicQuestion"):
        model = apps.get_model("joatham_messages", model_name)
        model.objects.filter(statut="resolu").update(statut="traite", date_traitement=final_status_date)
        model.objects.filter(statut="ignore").update(statut="archive", date_traitement=final_status_date)


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_messages", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="publicquestion",
            name="entreprise",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="publicquestion",
            name="date_traitement",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="suggestionsuperadmin",
            name="date_traitement",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(normalize_request_statuses, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="publicquestion",
            name="statut",
            field=models.CharField(
                choices=[
                    ("nouveau", "Nouveau"),
                    ("en_cours", "En cours"),
                    ("traite", "Traite"),
                    ("rejete", "Rejete"),
                    ("archive", "Archive"),
                ],
                default="nouveau",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="suggestionsuperadmin",
            name="statut",
            field=models.CharField(
                choices=[
                    ("nouveau", "Nouveau"),
                    ("en_cours", "En cours"),
                    ("traite", "Traite"),
                    ("rejete", "Rejete"),
                    ("archive", "Archive"),
                ],
                default="nouveau",
                max_length=20,
            ),
        ),
    ]
