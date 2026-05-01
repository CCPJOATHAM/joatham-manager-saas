import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_rename_core_exchan_devise__e3cf1a_idx_core_exchan_devise__cb06c8_idx"),
    ]

    operations = [
        migrations.AlterField(
            model_name="activitylog",
            name="entreprise",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="activity_logs",
                to="joatham_users.entreprise",
            ),
        ),
    ]
