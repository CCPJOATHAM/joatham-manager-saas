from django.http import Http404
from django.test import TestCase
from django.urls import reverse

from core.services.subscription import start_trial_for_entreprise
from joatham_billing.selectors.billing import (
    get_clients_for_billing_by_entreprise,
    get_facture_by_entreprise,
    get_factures_by_entreprise,
    get_paiements_by_facture_for_entreprise,
    get_services_by_entreprise,
)
from joatham_billing.models import Service
from joatham_products.models import Produit
from joatham_users.models import Abonnement

from .factories import create_client, create_entreprise, create_facture_sample, create_user


class BillingIsolationTests(TestCase):
    def setUp(self):
        self.entreprise_a = create_entreprise("Entreprise A")
        self.entreprise_b = create_entreprise("Entreprise B")
        self.user_a = create_user("user-a", "gestionnaire", self.entreprise_a)
        self.user_b = create_user("user-b", "gestionnaire", self.entreprise_b)
        self.plan = Abonnement.objects.create(nom="Billing", code="billing", prix=29, duree_jours=30, actif=True)
        start_trial_for_entreprise(entreprise=self.entreprise_a, plan=self.plan, utilisateur=self.user_a)
        start_trial_for_entreprise(entreprise=self.entreprise_b, plan=self.plan, utilisateur=self.user_b)
        self.client_a = create_client(self.entreprise_a, "Client A")
        self.client_b = create_client(self.entreprise_b, "Client B")
        self.service_a = Service.objects.create(nom="Service A", prix=100, entreprise=self.entreprise_a)
        self.service_b = Service.objects.create(nom="Service B", prix=200, entreprise=self.entreprise_b)
        self.product_a = Produit.objects.create(
            entreprise=self.entreprise_a,
            nom="Produit A",
            description="Produit A description",
            reference="PROD-A",
            prix_unitaire=100,
            quantite_stock=5,
            seuil_alerte=1,
        )
        self.product_b = Produit.objects.create(
            entreprise=self.entreprise_b,
            nom="Produit B",
            description="Produit B description",
            reference="PROD-B",
            prix_unitaire=200,
            quantite_stock=5,
            seuil_alerte=1,
        )
        self.facture_a = create_facture_sample(self.entreprise_a, self.user_a, self.client_a)
        self.facture_b = create_facture_sample(self.entreprise_b, self.user_b, self.client_b)

    def test_facture_selector_returns_only_same_entreprise(self):
        queryset_a = get_factures_by_entreprise(self.entreprise_a)
        queryset_b = get_factures_by_entreprise(self.entreprise_b)
        self.assertEqual(list(queryset_a), [self.facture_a])
        self.assertEqual(list(queryset_b), [self.facture_b])

    def test_get_facture_selector_prevents_cross_access(self):
        facture = get_facture_by_entreprise(self.entreprise_a, self.facture_a.id)
        self.assertEqual(facture.id, self.facture_a.id)
        with self.assertRaises(Http404):
            get_facture_by_entreprise(self.entreprise_a, self.facture_b.id)

    def test_client_and_service_selectors_are_scoped(self):
        self.assertEqual(list(get_clients_for_billing_by_entreprise(self.entreprise_a)), [self.client_a])
        self.assertEqual(list(get_services_by_entreprise(self.entreprise_a)), [self.service_a])

    def test_payment_selector_is_scoped_through_facture(self):
        self.assertEqual(list(get_paiements_by_facture_for_entreprise(self.entreprise_a, self.facture_a)), [])
        self.assertEqual(list(get_paiements_by_facture_for_entreprise(self.entreprise_a, self.facture_b)), [])

    def test_billing_views_still_use_scoped_reads(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("facture_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.client_a.nom)
        self.assertNotContains(response, self.client_b.nom)

    def test_add_facture_rejects_cross_tenant_product(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("add_facture"),
            {
                "client": self.client_a.id,
                "client_nom": "",
                "tva": "0",
                "remise": "0",
                "rabais": "0",
                "ristourne": "0",
                "product_id[]": [str(self.product_b.id)],
                "service_id[]": [""],
                "designation[]": [""],
                "quantite[]": ["1"],
                "prix[]": [""],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "produit selectionne est invalide")
