from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_users", "0018_rename_joatham_use_is_used_3d8595_idx_joatham_use_is_used_97b7ab_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="profile_photo",
            field=models.ImageField(blank=True, null=True, upload_to="profiles/"),
        ),
    ]
