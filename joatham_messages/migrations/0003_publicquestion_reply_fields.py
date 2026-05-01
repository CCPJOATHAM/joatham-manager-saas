import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_messages", "0002_public_question_company_status_tracking"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="publicquestion",
            name="reponse",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="publicquestion",
            name="date_reponse",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="publicquestion",
            name="repondu_par",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="questions_publiques_repondues",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
