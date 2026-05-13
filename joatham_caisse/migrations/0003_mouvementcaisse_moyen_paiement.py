from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("joatham_caisse", "0002_rename_cash_move_company_type_date_idx_cash_mov_ent_type_dt_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="mouvementcaisse",
            name="moyen_paiement",
            field=models.CharField(blank=True, db_index=True, default="cash", max_length=30),
        ),
        migrations.AddIndex(
            model_name="mouvementcaisse",
            index=models.Index(
                fields=["entreprise", "moyen_paiement", "date_mouvement"],
                name="cash_mov_ent_method_dt_idx",
            ),
        ),
    ]
