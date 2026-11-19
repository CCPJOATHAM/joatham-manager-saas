from django.db import migrations, models
from django.utils.translation import gettext_lazy as _


def reset_retired_language_preferences(apps, schema_editor):
    user = apps.get_model("joatham_users", "User")
    user.objects.using(schema_editor.connection.alias).filter(
        preferred_language__in=("pt", "es"),
    ).update(preferred_language="fr")


class Migration(migrations.Migration):
    dependencies = [
        ("joatham_users", "0020_useractivesession"),
    ]

    operations = [
        migrations.RunPython(reset_retired_language_preferences, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="preferred_language",
            field=models.CharField(
                _("langue preferee"),
                max_length=5,
                choices=[("fr", _("Français")), ("en", _("English"))],
                default="fr",
            ),
        ),
    ]
