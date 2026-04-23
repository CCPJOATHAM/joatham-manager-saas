from django.test import TestCase
from django.urls import reverse

from core.services.subscription import start_trial_for_entreprise
from joatham_billing.tests.factories import create_client, create_entreprise, create_user
from joatham_clients.services.clients_service import list_clients_for_entreprise
from joatham_clients.selectors.clients import get_clients_by_entreprise
from joatham_users.models import Abonnement


class ClientPermissionTests(TestCase):
    def setUp(self):
        self.entreprise_a = create_entreprise("Entreprise Clients A")
        self.entreprise_b = create_entreprise("Entreprise Clients B")
        self.gestionnaire_a = create_user("gestion-clients-a", "gestionnaire", self.entreprise_a)
        self.comptable_a = create_user("compta-clients-a", "comptable", self.entreprise_a)
        self.gestionnaire_b = create_user("gestion-clients-b", "gestionnaire", self.entreprise_b)
        self.plan = Abonnement.objects.create(nom="Clients", code="clients", prix=19, duree_jours=30, actif=True)
        start_trial_for_entreprise(entreprise=self.entreprise_a, plan=self.plan, utilisateur=self.gestionnaire_a)
        self.client_a = create_client(self.entreprise_a, "Client A")
        self.client_b = create_client(self.entreprise_b, "Client B")

    def test_comptable_cannot_access_clients_module(self):
        self.client.force_login(self.comptable_a)
        response = self.client.get(reverse("client_list"))
        self.assertEqual(response.status_code, 403)

    def test_gestionnaire_cannot_edit_other_entreprise_client(self):
        self.client.force_login(self.gestionnaire_a)
        response = self.client.get(reverse("edit_client", args=[self.client_b.id]))
        self.assertEqual(response.status_code, 404)

    def test_gestionnaire_can_list_own_clients(self):
        self.client.force_login(self.gestionnaire_a)
        response = self.client.get(reverse("client_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Client A")
        self.assertNotContains(response, "Client B")
        self.assertContains(response, "Ajouter un client")

    def test_client_selector_scopes_to_entreprise(self):
        self.assertEqual(list(get_clients_by_entreprise(self.entreprise_a)), [self.client_a])

    def test_client_service_returns_only_same_entreprise(self):
        self.assertEqual(list(list_clients_for_entreprise(self.entreprise_a)), [self.client_a])

    def test_client_list_displays_empty_state(self):
        empty_entreprise = create_entreprise("Entreprise Vide")
        empty_user = create_user("gestion-empty", "gestionnaire", empty_entreprise)
        start_trial_for_entreprise(entreprise=empty_entreprise, plan=self.plan, utilisateur=empty_user)

        self.client.force_login(empty_user)
        response = self.client.get(reverse("client_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucun client enregistre pour le moment")
        self.assertContains(response, "Ajouter un client")

    def test_client_search_filters_results_inside_same_entreprise(self):
        self.client.force_login(self.gestionnaire_a)
        response = self.client.get(reverse("client_list"), {"q": "Client A"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Client A")
        self.assertNotContains(response, "Client B")
