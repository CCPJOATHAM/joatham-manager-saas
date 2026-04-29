from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_platformsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformsettings",
            name="maintenance_allowed_ips",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="message_maintenance",
            field=models.TextField(
                blank=True,
                default="Nous effectuons une operation de maintenance afin d'ameliorer votre experience.",
            ),
        ),
    ]
