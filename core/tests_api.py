import importlib.util
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone


if importlib.util.find_spec("rest_framework") is not None:
    from rest_framework.test import APITestCase

    from core.services.subscription import activate_subscription_for_entreprise, start_trial_for_entreprise, suspend_subscription_for_entreprise
    from joatham_apprenants.models import Apprenant, Formation, InscriptionFormation
    from joatham_billing.tests.factories import create_client, create_entreprise, create_facture_sample, create_user
    from joatham_depenses.models import Depense
    from joatham_users.models import Abonnement


    @override_settings(REST_FRAMEWORK_AVAILABLE=True)
    class ApiV1Tests(APITestCase):
        def setUp(self):
            self.entreprise_a = create_entreprise("Entreprise API A")
            self.entreprise_b = create_entreprise("Entreprise API B")
            self.owner_a = create_user("owner-api-a", "proprietaire", self.entreprise_a)
            self.gestionnaire_a = create_user("gestion-api-a", "gestionnaire", self.entreprise_a)
            self.comptable_a = create_user("compta-api-a", "comptable", self.entreprise_a)
            self.gestionnaire_b = create_user("gestion-api-b", "gestionnaire", self.entreprise_b)
            self.plan = Abonnement.objects.create(nom="API", code="api", prix=30, duree_jours=30, actif=True)

            start_trial_for_entreprise(entreprise=self.entreprise_a, plan=self.plan, utilisateur=self.owner_a)
            activate_subscription_for_entreprise(entreprise=self.entreprise_b, plan=self.plan, utilisateur=self.gestionnaire_b)

            self.client_a = create_client(self.entreprise_a, "Client API A")
            self.client_b = create_client(self.entreprise_b, "Client API B")
            self.depense_a = Depense.objects.create(entreprise=self.entreprise_a, description="Internet", montant=Decimal("25.00"))
            Depense.objects.create(entreprise=self.entreprise_b, description="Transport", montant=Decimal("40.00"))
            self.facture_a = create_facture_sample(self.entreprise_a, self.gestionnaire_a, self.client_a, Decimal("100"))
            self.facture_b = create_facture_sample(self.entreprise_b, self.gestionnaire_b, self.client_b, Decimal("80"))

            self.apprenant_a = Apprenant.objects.create(entreprise=self.entreprise_a, nom="Alpha", prenom="A")
            self.apprenant_b = Apprenant.objects.create(entreprise=self.entreprise_b, nom="Beta", prenom="B")
            self.formation_a = Formation.objects.create(entreprise=self.entreprise_a, nom="Excel", prix=Decimal("70.00"))
            self.formation_b = Formation.objects.create(entreprise=self.entreprise_b, nom="Word", prix=Decimal("55.00"))
            self.inscription_a = InscriptionFormation.objects.create(
                entreprise=self.entreprise_a,
                apprenant=self.apprenant_a,
                formation=self.formation_a,
                montant_prevu=Decimal("70.00"),
                montant_paye=Decimal("20.00"),
                facture=self.facture_a,
            )
            InscriptionFormation.objects.create(
                entreprise=self.entreprise_b,
                apprenant=self.apprenant_b,
                formation=self.formation_b,
                montant_prevu=Decimal("55.00"),
                montant_paye=Decimal("0.00"),
                facture=self.facture_b,
            )

        def test_auth_is_required_for_api(self):
            response = self.client.get("/api/clients/")
            self.assertIn(response.status_code, {401, 403})

        def test_clients_list_is_scoped_to_entreprise(self):
            self.client.force_authenticate(self.gestionnaire_a)
            response = self.client.get("/api/clients/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["nom"], "Client API A")

        def test_client_creation_uses_service_and_permission(self):
            self.client.force_authenticate(self.gestionnaire_a)
            response = self.client.post(
                "/api/clients/",
                {"nom": "Client API New", "telephone": "+243999", "email": "new@example.com"},
                format="json",
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data["nom"], "Client API New")

        def test_comptable_cannot_create_client_via_api(self):
            self.client.force_authenticate(self.comptable_a)
            response = self.client.post("/api/clients/", {"nom": "Nope"}, format="json")
            self.assertEqual(response.status_code, 403)

        def test_depenses_list_is_scoped_to_entreprise(self):
            self.client.force_authenticate(self.comptable_a)
            response = self.client.get("/api/depenses/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["description"], "Internet")

        def test_factures_list_and_detail_are_scoped(self):
            self.client.force_authenticate(self.comptable_a)
            list_response = self.client.get("/api/factures/")
            detail_response = self.client.get(f"/api/factures/{self.facture_a.id}/")
            cross_response = self.client.get(f"/api/factures/{self.facture_b.id}/")

            self.assertEqual(list_response.status_code, 200)
            self.assertEqual(list_response.data["count"], 1)
            self.assertEqual(detail_response.status_code, 200)
            self.assertEqual(detail_response.data["numero"], self.facture_a.numero)
            self.assertEqual(cross_response.status_code, 404)

        def test_apprenants_endpoints_are_scoped(self):
            self.client.force_authenticate(self.comptable_a)

            apprenants_response = self.client.get("/api/apprenants/")
            formations_response = self.client.get("/api/formations/")
            inscriptions_response = self.client.get("/api/inscriptions/")

            self.assertEqual(apprenants_response.status_code, 200)
            self.assertEqual(apprenants_response.data["count"], 1)
            self.assertEqual(apprenants_response.data["results"][0]["nom"], "Alpha")
            self.assertEqual(formations_response.data["results"][0]["nom"], "Excel")
            self.assertEqual(inscriptions_response.data["results"][0]["formation_nom"], "Excel")

        def test_inscriptions_support_basic_filters(self):
            self.client.force_authenticate(self.comptable_a)
            response = self.client.get(
                "/api/inscriptions/",
                {"formation": self.formation_a.id, "statut": self.inscription_a.statut, "apprenant": self.apprenant_a.id},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["id"], self.inscription_a.id)

        def test_module_policy_blocks_suspended_subscription(self):
            suspend_subscription_for_entreprise(entreprise=self.entreprise_a, utilisateur=self.owner_a)
            self.client.force_authenticate(self.gestionnaire_a)
            response = self.client.get("/api/clients/")
            self.assertEqual(response.status_code, 403)

        def test_api_permissions_match_business_permissions(self):
            self.client.force_authenticate(self.comptable_a)
            response = self.client.get("/api/clients/")
            self.assertEqual(response.status_code, 403)

        def test_factures_endpoint_supports_existing_filters(self):
            self.client.force_authenticate(self.comptable_a)
            response = self.client.get(
                "/api/factures/",
                {
                    "search": self.facture_a.numero,
                    "date_debut": timezone.localdate().isoformat(),
                    "date_fin": timezone.localdate().isoformat(),
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 1)
