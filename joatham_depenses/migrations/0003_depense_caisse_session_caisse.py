# Generated manually to add optional cashbox linkage for expenses.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_caisse", "0002_rename_cash_move_company_type_date_idx_cash_mov_ent_type_dt_idx_and_more"),
        ("joatham_depenses", "0002_alter_depense_entreprise"),
    ]

    operations = [
        migrations.AddField(
            model_name="depense",
            name="caisse",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="depenses",
                to="joatham_caisse.caisse",
            ),
        ),
        migrations.AddField(
            model_name="depense",
            name="session_caisse",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="depenses",
                to="joatham_caisse.sessioncaisse",
            ),
        ),
    ]
