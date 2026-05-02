import tempfile
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import ActivityLog
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Entreprise, EntrepriseInvitation, User

from .models import MessageAttachment, PublicQuestion, SuggestionSuperAdmin
from .services.messages import create_conversation, create_invitation_from_public_question


class MessageTenancyTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_root.cleanup)

        self.entreprise_a = create_entreprise("Entreprise Messages A")
        self.entreprise_b = create_entreprise("Entreprise Messages B")
        self.owner_a = create_user("owner-msg-a", User.Role.PROPRIETAIRE, self.entreprise_a)
        self.manager_a = create_user("manager-msg-a", User.Role.GESTIONNAIRE, self.entreprise_a)
        self.owner_b = create_user("owner-msg-b", User.Role.PROPRIETAIRE, self.entreprise_b)

    def test_user_never_sees_other_company_conversation(self):
        conversation = create_conversation(
            entreprise=self.entreprise_a,
            creator=self.owner_a,
            subject="Conversation A",
            participant_ids=[self.manager_a.id],
            content="Message prive A",
        )

        self.client.force_login(self.owner_b)
        response = self.client.get(reverse("message_conversation_detail", args=[conversation.id]))

        self.assertEqual(response.status_code, 404)

    def test_attachment_download_is_limited_to_company_participants(self):
        uploaded_file = SimpleUploadedFile("note.txt", b"contenu", content_type="text/plain")
        conversation = create_conversation(
            entreprise=self.entreprise_a,
            creator=self.owner_a,
            subject="Avec piece jointe",
            participant_ids=[self.manager_a.id],
            content="Voir la piece jointe",
            attachments=[uploaded_file],
        )
        attachment = MessageAttachment.objects.get(message__conversation=conversation)

        self.client.force_login(self.manager_a)
        response = self.client.get(reverse("message_attachment_download", args=[attachment.id]))

        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response.headers["Content-Disposition"])
        finally:
            response.close()

        self.client.force_login(self.owner_b)
        denied = self.client.get(reverse("message_attachment_download", args=[attachment.id]))
        try:
            self.assertEqual(denied.status_code, 404)
        finally:
            denied.close()


class SuggestionAndPublicQuestionTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Suggestions")
        self.owner = create_user("owner-suggestion", User.Role.PROPRIETAIRE, self.entreprise)
        self.manager = create_user("manager-suggestion", User.Role.GESTIONNAIRE, self.entreprise)
        self.super_admin = User.objects.create_user(
            username="super-messages",
            email="super-messages@example.com",
            password="testpass123",
            role=User.Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )

    def test_owner_can_send_suggestion_to_super_admin(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("message_suggestion_create"),
            {"sujet": "Besoin reporting", "message": "Ajouter un rapport mensuel."},
        )

        self.assertRedirects(response, reverse("message_suggestion_create"))
        suggestion = SuggestionSuperAdmin.objects.get()
        self.assertEqual(suggestion.entreprise, self.entreprise)
        self.assertEqual(suggestion.utilisateur, self.owner)
        self.assertEqual(suggestion.statut, SuggestionSuperAdmin.Statut.NOUVEAU)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="suggestion_creee",
                objet_id=suggestion.id,
            ).exists()
        )

    def test_non_owner_cannot_send_suggestion(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("message_suggestion_create"),
            {"sujet": "Besoin reporting", "message": "Ajouter un rapport mensuel."},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(SuggestionSuperAdmin.objects.exists())

    def test_public_question_form_does_not_require_account_and_redirects_to_success(self):
        response = self.client.post(
            reverse("public_question_create"),
            {
                "nom": "Prospect",
                "email": "Prospect@Example.com",
                "telephone": "+243000",
                "entreprise": "Prospect SARL",
                "sujet": "Question essai",
                "message": "Comment fonctionne l'essai ?",
            },
        )

        self.assertRedirects(response, reverse("public_question_success"))
        question = PublicQuestion.objects.get()
        self.assertEqual(question.email, "prospect@example.com")
        self.assertEqual(question.entreprise, "Prospect SARL")
        self.assertEqual(question.statut, PublicQuestion.Statut.NOUVEAU)
        self.assertEqual(question.lead_status, PublicQuestion.LeadStatus.NOUVEAU)
        self.assertTrue(question.is_lead)
        self.assertEqual(question.source, "question_publique")
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise__isnull=True,
                action="question_publique_creee",
                objet_id=question.id,
            ).exists()
        )

    def test_public_question_success_page_shows_signup_action(self):
        response = self.client.get(reverse("public_question_success"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/signup/")

    def test_public_question_rejects_missing_required_fields(self):
        response = self.client.post(
            reverse("public_question_create"),
            {
                "nom": "",
                "email": "",
                "sujet": "",
                "message": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PublicQuestion.objects.exists())

    def test_public_question_honeypot_blocks_spam_submission(self):
        response = self.client.post(
            reverse("public_question_create"),
            {
                "nom": "Bot Prospect",
                "email": "bot@example.com",
                "telephone": "+243000",
                "entreprise": "Bot SARL",
                "sujet": "Question spam",
                "message": "Message assez long pour passer la validation.",
                "site_web": "https://spam.example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PublicQuestion.objects.exists())

    def test_super_admin_can_see_suggestions_and_public_questions(self):
        SuggestionSuperAdmin.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.owner,
            sujet="Suggestion visible",
            message="Message suggestion",
        )
        PublicQuestion.objects.create(
            nom="Prospect",
            email="prospect@example.com",
            sujet="Question visible",
            message="Message question",
        )

        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("super_admin_messages"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Suggestion visible")
        self.assertContains(response, "Question visible")

    def test_non_authorized_user_cannot_access_super_admin_messages(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("super_admin_messages"))

        self.assertEqual(response.status_code, 403)

    def test_super_admin_can_update_suggestion_status(self):
        suggestion = SuggestionSuperAdmin.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.owner,
            sujet="Suggestion a traiter",
            message="Message suggestion a traiter",
        )

        self.client.force_login(self.super_admin)
        response = self.client.post(
            reverse("super_admin_messages"),
            {
                "item_type": "suggestion",
                "item_id": suggestion.id,
                "status": SuggestionSuperAdmin.Statut.TRAITE,
            },
        )

        self.assertRedirects(response, reverse("super_admin_messages"))
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.statut, SuggestionSuperAdmin.Statut.TRAITE)
        self.assertIsNotNone(suggestion.date_traitement)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.super_admin,
                action="suggestion_statut_modifie",
                objet_id=suggestion.id,
            ).exists()
        )

    def test_super_admin_can_update_public_question_status(self):
        question = PublicQuestion.objects.create(
            nom="Prospect",
            email="prospect@example.com",
            entreprise="Prospect SARL",
            sujet="Question a traiter",
            message="Message question a traiter",
        )

        self.client.force_login(self.super_admin)
        response = self.client.post(
            reverse("super_admin_messages"),
            {
                "item_type": "question",
                "item_id": question.id,
                "status": PublicQuestion.Statut.ARCHIVE,
            },
        )

        self.assertRedirects(response, reverse("super_admin_messages"))
        question.refresh_from_db()
        self.assertEqual(question.statut, PublicQuestion.Statut.ARCHIVE)
        self.assertIsNotNone(question.date_traitement)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise__isnull=True,
                utilisateur=self.super_admin,
                action="question_publique_statut_modifie",
                objet_id=question.id,
            ).exists()
        )

    def test_super_admin_filters_requests_by_type_and_search(self):
        SuggestionSuperAdmin.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.owner,
            sujet="Reporting avance",
            message="Ajouter un tableau de bord mensuel.",
        )
        PublicQuestion.objects.create(
            nom="Prospect",
            email="prospect@example.com",
            sujet="Question visible autre",
            message="Message question publique.",
        )

        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("super_admin_messages"), {"type": "suggestion", "q": "Reporting"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reporting avance")
        self.assertNotContains(response, "Question visible autre")

    def test_super_admin_lead_stats_are_correct(self):
        PublicQuestion.objects.create(
            nom="Prospect nouveau",
            email="nouveau@example.com",
            sujet="Lead nouveau",
            message="Message lead nouveau.",
            lead_status=PublicQuestion.LeadStatus.NOUVEAU,
        )
        PublicQuestion.objects.create(
            nom="Prospect en cours",
            email="encours@example.com",
            sujet="Lead en cours",
            message="Message lead en cours.",
            lead_status=PublicQuestion.LeadStatus.EN_COURS,
        )
        PublicQuestion.objects.create(
            nom="Prospect converti",
            email="converti@example.com",
            sujet="Lead converti",
            message="Message lead converti.",
            lead_status=PublicQuestion.LeadStatus.CONVERTI,
        )

        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("super_admin_messages"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["lead_stats"]["total"], 3)
        self.assertEqual(response.context["lead_stats"]["nouveau_count"], 1)
        self.assertEqual(response.context["lead_stats"]["en_cours_count"], 1)
        self.assertEqual(response.context["lead_stats"]["converti_count"], 1)

    def test_super_admin_filters_public_questions_by_lead_status(self):
        PublicQuestion.objects.create(
            nom="Prospect nouveau",
            email="nouveau@example.com",
            sujet="Lead encore nouveau",
            message="Message lead nouveau.",
            lead_status=PublicQuestion.LeadStatus.NOUVEAU,
        )
        PublicQuestion.objects.create(
            nom="Prospect converti",
            email="converti@example.com",
            sujet="Lead deja converti",
            message="Message lead converti.",
            lead_status=PublicQuestion.LeadStatus.CONVERTI,
        )
        SuggestionSuperAdmin.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.owner,
            sujet="Suggestion hors CRM",
            message="Message suggestion hors CRM.",
        )

        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("super_admin_messages"), {"status": PublicQuestion.LeadStatus.CONVERTI})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_lead_status"], PublicQuestion.LeadStatus.CONVERTI)
        self.assertContains(response, "Lead deja converti")
        self.assertNotContains(response, "Lead encore nouveau")
        self.assertNotContains(response, "Suggestion hors CRM")

    def test_super_admin_can_update_public_question_lead_status(self):
        question = PublicQuestion.objects.create(
            nom="Prospect",
            email="prospect@example.com",
            sujet="Lead a convertir",
            message="Message lead a convertir.",
        )

        self.client.force_login(self.super_admin)
        response = self.client.post(
            reverse("super_admin_update_lead_status", args=[question.id]),
            {"lead_status": PublicQuestion.LeadStatus.CONVERTI},
            HTTP_REFERER=reverse("super_admin_messages") + "?status=nouveau",
        )

        self.assertRedirects(
            response,
            reverse("super_admin_messages") + "?status=nouveau",
            fetch_redirect_response=False,
        )
        question.refresh_from_db()
        self.assertEqual(question.lead_status, PublicQuestion.LeadStatus.CONVERTI)

    def test_non_authorized_user_cannot_update_public_question_lead_status(self):
        question = PublicQuestion.objects.create(
            nom="Prospect",
            email="prospect@example.com",
            sujet="Lead protege",
            message="Message lead protege.",
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("super_admin_update_lead_status", args=[question.id]),
            {"lead_status": PublicQuestion.LeadStatus.CONVERTI},
        )

        self.assertEqual(response.status_code, 403)
        question.refresh_from_db()
        self.assertEqual(question.lead_status, PublicQuestion.LeadStatus.NOUVEAU)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="support@joatham.local",
        JOATHAM_APP_URL="https://app.joatham.test",
    )
    def test_public_question_invitation_lock_query_does_not_select_related_nullable_invitation(self):
        class LockedQuestionQuery:
            def __init__(self, locked_question):
                self.locked_question = locked_question

            def select_related(self, *args, **kwargs):
                raise AssertionError("select_related must not be chained after select_for_update for invitation.")

            def get(self, **kwargs):
                if kwargs != {"id": self.locked_question.id}:
                    raise AssertionError(f"Unexpected lock query filters: {kwargs}")
                return self.locked_question

        question = PublicQuestion.objects.create(
            nom="Prospect PostgreSQL",
            email="postgres@example.com",
            sujet="Compatibilite verrou",
            message="Message pour verifier la compatibilite PostgreSQL.",
        )

        with patch(
            "joatham_messages.services.messages.PublicQuestion.objects.select_for_update",
            return_value=LockedQuestionQuery(question),
        ):
            result = create_invitation_from_public_question(question=question, created_by=self.super_admin)

        question.refresh_from_db()
        self.assertTrue(result.created)
        self.assertIsNotNone(question.invitation)
        self.assertEqual(question.lead_status, PublicQuestion.LeadStatus.EN_COURS)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="support@joatham.local",
        JOATHAM_APP_URL="https://app.joatham.test",
    )
    def test_super_admin_can_create_invitation_from_public_question(self):
        mail.outbox = []
        question = PublicQuestion.objects.create(
            nom="Prospect Invite",
            email="invite@example.com",
            sujet="Invitation souhaitee",
            message="Je veux recevoir une invitation securisee.",
        )

        self.client.force_login(self.super_admin)
        response = self.client.post(reverse("super_admin_send_public_question_invitation", args=[question.id]))

        self.assertRedirects(response, reverse("super_admin_messages"))
        question.refresh_from_db()
        invitation = question.invitation
        self.assertIsNotNone(invitation)
        self.assertEqual(invitation.email, "invite@example.com")
        self.assertEqual(invitation.full_name, "Prospect Invite")
        self.assertEqual(invitation.source, "question_publique")
        self.assertEqual(question.lead_status, PublicQuestion.LeadStatus.EN_COURS)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["invite@example.com"])
        self.assertIn("https://app.joatham.test/signup/?invitation=", mail.outbox[0].body)
        self.assertIn("Activer mon compte", mail.outbox[0].alternatives[0][0])
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise__isnull=True,
                utilisateur=self.super_admin,
                action="question_publique_invitation_envoyee",
                objet_id=question.id,
            ).exists()
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="support@joatham.local",
        JOATHAM_APP_URL="https://app.joatham.test",
    )
    def test_public_question_invitation_is_not_duplicated(self):
        mail.outbox = []
        invitation = EntrepriseInvitation.objects.create(
            email="existing@example.com",
            full_name="Prospect Existing",
            source="question_publique",
        )
        question = PublicQuestion.objects.create(
            nom="Prospect Existing",
            email="existing@example.com",
            sujet="Invitation existante",
            message="Message invitation existante.",
            invitation=invitation,
        )

        self.client.force_login(self.super_admin)
        response = self.client.post(reverse("super_admin_send_public_question_invitation", args=[question.id]))

        self.assertRedirects(response, reverse("super_admin_messages"))
        question.refresh_from_db()
        self.assertEqual(question.invitation, invitation)
        self.assertEqual(question.lead_status, PublicQuestion.LeadStatus.EN_COURS)
        self.assertEqual(EntrepriseInvitation.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="support@joatham.local",
        JOATHAM_APP_URL="https://app.joatham.test",
    )
    def test_public_question_invitation_does_not_create_company_or_user(self):
        question = PublicQuestion.objects.create(
            nom="Prospect Sans Creation",
            email="no-create@example.com",
            sujet="Invitation sans creation",
            message="Je veux seulement recevoir une invitation.",
        )
        company_count = Entreprise.objects.count()
        user_count = User.objects.count()

        self.client.force_login(self.super_admin)
        response = self.client.post(reverse("super_admin_send_public_question_invitation", args=[question.id]))

        self.assertRedirects(response, reverse("super_admin_messages"))
        self.assertEqual(Entreprise.objects.count(), company_count)
        self.assertEqual(User.objects.count(), user_count)

    def test_non_authorized_user_cannot_send_public_question_invitation(self):
        question = PublicQuestion.objects.create(
            nom="Prospect Protege",
            email="protected@example.com",
            sujet="Invitation protegee",
            message="Message invitation protegee.",
        )

        self.client.force_login(self.owner)
        response = self.client.post(reverse("super_admin_send_public_question_invitation", args=[question.id]))

        self.assertEqual(response.status_code, 403)
        question.refresh_from_db()
        self.assertIsNone(question.invitation)
        self.assertFalse(EntrepriseInvitation.objects.exists())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="support@joatham.local",
        JOATHAM_APP_URL="https://app.joatham.test",
    )
    def test_converted_public_question_cannot_send_invitation(self):
        mail.outbox = []
        question = PublicQuestion.objects.create(
            nom="Prospect Converti",
            email="converted@example.com",
            sujet="Lead converti",
            message="Message lead deja converti.",
            lead_status=PublicQuestion.LeadStatus.CONVERTI,
        )

        self.client.force_login(self.super_admin)
        response = self.client.post(reverse("super_admin_send_public_question_invitation", args=[question.id]))

        self.assertRedirects(response, reverse("super_admin_messages"))
        question.refresh_from_db()
        self.assertIsNone(question.invitation)
        self.assertFalse(EntrepriseInvitation.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="support@joatham.local",
        JOATHAM_APP_URL="https://app.joatham.test",
    )
    def test_public_question_invitation_email_error_is_handled(self):
        mail.outbox = []
        question = PublicQuestion.objects.create(
            nom="Prospect Email Down",
            email="email-down@example.com",
            sujet="Invitation erreur email",
            message="Message invitation avec erreur email.",
        )

        self.client.force_login(self.super_admin)
        with self.assertLogs("joatham_users.services.invitations", level="ERROR") as logs:
            with patch("joatham_users.services.invitations.EmailMultiAlternatives.send", side_effect=Exception("smtp down")):
                response = self.client.post(reverse("super_admin_send_public_question_invitation", args=[question.id]))

        self.assertRedirects(response, reverse("super_admin_messages"))
        question.refresh_from_db()
        self.assertIsNone(question.invitation)
        self.assertEqual(question.lead_status, PublicQuestion.LeadStatus.NOUVEAU)
        self.assertFalse(EntrepriseInvitation.objects.exists())
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn("invitation=", "\n".join(logs.output))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_FROM_EMAIL="support@joatham.local")
    def test_super_admin_can_reply_to_public_question(self):
        mail.outbox = []
        question = PublicQuestion.objects.create(
            nom="Prospect",
            email="prospect@example.com",
            telephone="+243000",
            entreprise="Prospect SARL",
            sujet="Question avant inscription",
            message="Je veux comprendre le fonctionnement de JOATHAM Manager.",
        )

        self.client.force_login(self.super_admin)
        response = self.client.post(
            reverse("super_admin_public_question_reply", args=[question.id]),
            {"reponse": "Merci pour votre question. JOATHAM Manager permet de gerer votre activite SaaS simplement."},
        )

        self.assertRedirects(response, reverse("super_admin_messages"))
        question.refresh_from_db()
        self.assertEqual(question.statut, PublicQuestion.Statut.TRAITE)
        self.assertEqual(question.repondu_par, self.super_admin)
        self.assertIsNotNone(question.date_reponse)
        self.assertIsNotNone(question.date_traitement)
        self.assertIn("JOATHAM Manager permet", question.reponse)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["prospect@example.com"])
        self.assertIn("JOATHAM Manager permet", mail.outbox[0].body)
        self.assertEqual(len(mail.outbox[0].alternatives), 1)
        html_body, html_mimetype = mail.outbox[0].alternatives[0]
        self.assertEqual(html_mimetype, "text/html")
        self.assertIn("Creer un compte", html_body)
        self.assertIn("https://app.joatham.com/signup/", html_body)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise__isnull=True,
                utilisateur=self.super_admin,
                action="question_publique_repondue",
                objet_id=question.id,
            ).exists()
        )

    def test_non_authorized_user_cannot_reply_to_public_question(self):
        question = PublicQuestion.objects.create(
            nom="Prospect",
            email="prospect@example.com",
            sujet="Question protegee",
            message="Message question publique protegee.",
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("super_admin_public_question_reply", args=[question.id]),
            {"reponse": "Reponse interdite pour utilisateur non super admin."},
        )

        self.assertEqual(response.status_code, 403)
        question.refresh_from_db()
        self.assertEqual(question.statut, PublicQuestion.Statut.NOUVEAU)
        self.assertEqual(question.reponse, "")
        self.assertIsNone(question.date_reponse)
        self.assertIsNone(question.date_traitement)
        self.assertIsNone(question.repondu_par)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_FROM_EMAIL="support@joatham.local")
    def test_audit_failure_does_not_block_public_question_reply(self):
        mail.outbox = []
        question = PublicQuestion.objects.create(
            nom="Prospect",
            email="prospect@example.com",
            sujet="Question audit",
            message="Message question publique avec audit.",
        )

        self.client.force_login(self.super_admin)
        with patch("core.audit.ActivityLog.objects.create", side_effect=Exception("audit down")):
            response = self.client.post(
                reverse("super_admin_public_question_reply", args=[question.id]),
                {"reponse": "Reponse envoyee meme si le journal audit echoue."},
            )

        self.assertRedirects(response, reverse("super_admin_messages"))
        question.refresh_from_db()
        self.assertEqual(question.statut, PublicQuestion.Statut.TRAITE)
        self.assertEqual(question.repondu_par, self.super_admin)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_FROM_EMAIL="support@joatham.local")
    def test_email_failure_keeps_question_unanswered_and_shows_message(self):
        mail.outbox = []
        question = PublicQuestion.objects.create(
            nom="Prospect",
            email="prospect@example.com",
            sujet="Question email",
            message="Message question publique avec echec email.",
        )

        self.client.force_login(self.super_admin)
        with patch("joatham_messages.services.messages.EmailMultiAlternatives.send", side_effect=Exception("smtp down")):
            response = self.client.post(
                reverse("super_admin_public_question_reply", args=[question.id]),
                {"reponse": "Reponse qui ne doit pas etre marquee comme envoyee si email echoue."},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La reponse n&#x27;a pas pu etre envoyee par email")
        question.refresh_from_db()
        self.assertEqual(question.statut, PublicQuestion.Statut.NOUVEAU)
        self.assertEqual(question.reponse, "")
        self.assertIsNone(question.date_reponse)
        self.assertIsNone(question.date_traitement)
        self.assertIsNone(question.repondu_par)
