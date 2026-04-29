from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_platformsettings_maintenance_details"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformsettings",
            name="maintenance_modules",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
