from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_products", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="produit",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
    ]
