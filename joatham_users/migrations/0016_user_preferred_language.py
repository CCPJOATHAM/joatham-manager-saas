from django.db import migrations, models
import django.utils.translation


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_users", "0015_saas_plan_limits_subscription_renewal"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="preferred_language",
            field=models.CharField(
                choices=[
                    ("fr", django.utils.translation.gettext_lazy("Français")),
                    ("en", django.utils.translation.gettext_lazy("English")),
                    ("pt", django.utils.translation.gettext_lazy("Português")),
                    ("es", django.utils.translation.gettext_lazy("Español")),
                ],
                default="fr",
                max_length=5,
                verbose_name=django.utils.translation.gettext_lazy("langue preferee"),
            ),
        ),
    ]
