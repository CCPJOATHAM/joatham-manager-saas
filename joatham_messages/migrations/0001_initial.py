import django.db.models.deletion
import joatham_messages.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("joatham_users", "0016_user_preferred_language"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Conversation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sujet", models.CharField(max_length=180)),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
                (
                    "cree_par",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="conversations_creees",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conversations",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "participants",
                    models.ManyToManyField(
                        blank=True,
                        related_name="message_conversations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-date_modification", "-id"],
            },
        ),
        migrations.CreateModel(
            name="PublicQuestion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=150)),
                ("email", models.EmailField(max_length=254)),
                ("telephone", models.CharField(blank=True, default="", max_length=50)),
                ("sujet", models.CharField(max_length=180)),
                ("message", models.TextField()),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("nouveau", "Nouveau"),
                            ("en_cours", "En cours"),
                            ("resolu", "Resolu"),
                            ("ignore", "Ignore"),
                        ],
                        default="nouveau",
                        max_length=20,
                    ),
                ),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-date_creation", "-id"],
            },
        ),
        migrations.CreateModel(
            name="SuggestionSuperAdmin",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sujet", models.CharField(max_length=180)),
                ("message", models.TextField()),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("nouveau", "Nouveau"),
                            ("en_cours", "En cours"),
                            ("resolu", "Resolu"),
                            ("ignore", "Ignore"),
                        ],
                        default="nouveau",
                        max_length=20,
                    ),
                ),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="suggestions_super_admin",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "utilisateur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="suggestions_super_admin",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-date_creation", "-id"],
            },
        ),
        migrations.CreateModel(
            name="Message",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contenu", models.TextField()),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                (
                    "entreprise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages_internes",
                        to="joatham_users.entreprise",
                    ),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="joatham_messages.conversation",
                    ),
                ),
                (
                    "expediteur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="messages_envoyes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "lecteurs",
                    models.ManyToManyField(
                        blank=True,
                        related_name="messages_lus",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["date_creation", "id"],
            },
        ),
        migrations.CreateModel(
            name="MessageAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fichier", models.FileField(upload_to=joatham_messages.models.message_attachment_upload_to)),
                ("nom_original", models.CharField(max_length=255)),
                ("type_contenu", models.CharField(blank=True, default="", max_length=120)),
                ("taille", models.PositiveIntegerField(default=0)),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                (
                    "message",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pieces_jointes",
                        to="joatham_messages.message",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
            },
        ),
        migrations.AddIndex(
            model_name="conversation",
            index=models.Index(fields=["entreprise", "-date_modification"], name="joatham_mes_entrepr_705580_idx"),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(fields=["entreprise", "date_creation"], name="joatham_mes_entrepr_f3ae1f_idx"),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(fields=["conversation", "date_creation"], name="joatham_mes_convers_970345_idx"),
        ),
        migrations.AddIndex(
            model_name="publicquestion",
            index=models.Index(fields=["statut", "-date_creation"], name="joatham_mes_statut_169e93_idx"),
        ),
        migrations.AddIndex(
            model_name="publicquestion",
            index=models.Index(fields=["email", "-date_creation"], name="joatham_mes_email_9ac2b5_idx"),
        ),
        migrations.AddIndex(
            model_name="suggestionsuperadmin",
            index=models.Index(fields=["statut", "-date_creation"], name="joatham_mes_statut_e59101_idx"),
        ),
        migrations.AddIndex(
            model_name="suggestionsuperadmin",
            index=models.Index(fields=["entreprise", "-date_creation"], name="joatham_mes_entrepr_8d4d96_idx"),
        ),
    ]
