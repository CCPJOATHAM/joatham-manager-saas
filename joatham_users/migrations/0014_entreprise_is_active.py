from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_users", "0013_user_email_verified_user_email_verified_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="entreprise",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
    ]
