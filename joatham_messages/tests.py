import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import User

from .models import MessageAttachment, PublicQuestion, SuggestionSuperAdmin
from .services.messages import create_conversation


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

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])

        self.client.force_login(self.owner_b)
        denied = self.client.get(reverse("message_attachment_download", args=[attachment.id]))
        self.assertEqual(denied.status_code, 404)


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

    def test_non_owner_cannot_send_suggestion(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("message_suggestion_create"),
            {"sujet": "Besoin reporting", "message": "Ajouter un rapport mensuel."},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(SuggestionSuperAdmin.objects.exists())

    def test_public_question_form_does_not_require_account(self):
        response = self.client.post(
            reverse("public_question_create"),
            {
                "nom": "Prospect",
                "email": "prospect@example.com",
                "telephone": "+243000",
                "sujet": "Question essai",
                "message": "Comment fonctionne l'essai ?",
            },
        )

        self.assertEqual(response.status_code, 200)
        question = PublicQuestion.objects.get()
        self.assertEqual(question.email, "prospect@example.com")
        self.assertEqual(question.statut, PublicQuestion.Statut.NOUVEAU)

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
