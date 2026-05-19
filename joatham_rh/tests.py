from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.services.product_policy import can_access_module
from core.services.subscription import (
    PREMIUM_PLAN_CODE,
    activate_subscription_for_entreprise,
    get_default_paid_plans,
)
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement

from .models import Employe, Presence
from .selectors.rh import get_employes_by_entreprise
from .services.rh import RhOperationError, create_employe, create_poste, record_presence


class RhFoundationTests(TestCase):
    def setUp(self):
        self.entreprise_a = create_entreprise("Entreprise RH A")
        self.entreprise_b = create_entreprise("Entreprise RH B")
        self.owner_a = create_user("owner-rh-a", "proprietaire", self.entreprise_a)
        self.manager_a = create_user("manager-rh-a", "gestionnaire", self.entreprise_a)
        self.owner_b = create_user("owner-rh-b", "proprietaire", self.entreprise_b)
        self.premium_plan = Abonnement.objects.create(
            nom="Premium RH",
            code=PREMIUM_PLAN_CODE,
            prix=99,
            duree_jours=30,
            actif=True,
            modules_inclus=["dashboard", "rh", "hr", "ressources_humaines", "human_resources"],
        )
        activate_subscription_for_entreprise(
            entreprise=self.entreprise_a,
            plan=self.premium_plan,
            utilisateur=self.owner_a,
        )
        activate_subscription_for_entreprise(
            entreprise=self.entreprise_b,
            plan=self.premium_plan,
            utilisateur=self.owner_b,
        )

    def _create_poste(self, entreprise=None, nom="Gestionnaire"):
        return create_poste(
            entreprise=entreprise or self.entreprise_a,
            nom=nom,
            description="Suivi operationnel",
            utilisateur=self.owner_a,
        )

    def _create_employe(self, entreprise=None, matricule="RH-001", nom="Mavungu"):
        entreprise = entreprise or self.entreprise_a
        poste = self._create_poste(entreprise=entreprise, nom=f"Poste {matricule} {nom}")
        return create_employe(
            entreprise=entreprise,
            matricule=matricule,
            nom=nom,
            prenom="Junior",
            poste=poste,
            type_contrat=Employe.TypeContrat.CDI,
            date_embauche=date(2026, 1, 10),
            salaire_base=Decimal("150.00"),
            statut=Employe.Statut.ACTIF,
            utilisateur=self.owner_a,
        )

    def test_default_premium_plan_includes_rh_aliases(self):
        premium = next(plan for plan in get_default_paid_plans() if plan["code"] == PREMIUM_PLAN_CODE)

        self.assertIn("rh", premium["modules_inclus"])
        self.assertIn("hr", premium["modules_inclus"])
        self.assertIn("ressources_humaines", premium["modules_inclus"])
        self.assertIn("human_resources", premium["modules_inclus"])

    def test_rh_aliases_grant_same_access_on_premium_plan(self):
        self.assertTrue(can_access_module(self.owner_a, "rh"))
        self.assertTrue(can_access_module(self.owner_a, "hr"))
        self.assertTrue(can_access_module(self.owner_a, "ressources_humaines"))
        self.assertTrue(can_access_module(self.owner_a, "human_resources"))

    def test_create_poste(self):
        poste = self._create_poste(nom="Caissier")

        self.assertEqual(poste.entreprise, self.entreprise_a)
        self.assertEqual(poste.nom, "Caissier")
        self.assertTrue(poste.actif)

    def test_create_employe_valid(self):
        employe = self._create_employe()

        self.assertEqual(employe.entreprise, self.entreprise_a)
        self.assertEqual(employe.matricule, "RH-001")
        self.assertEqual(employe.salaire_base, Decimal("150.00"))
        self.assertEqual(employe.statut, Employe.Statut.ACTIF)

    def test_create_employe_requires_name(self):
        poste = self._create_poste()

        with self.assertRaisesMessage(RhOperationError, "Le nom est obligatoire."):
            create_employe(
                entreprise=self.entreprise_a,
                matricule="RH-002",
                nom="",
                prenom="Junior",
                poste=poste,
                date_embauche=date(2026, 1, 10),
                utilisateur=self.owner_a,
            )

    def test_create_employe_rejects_negative_salary(self):
        poste = self._create_poste()

        with self.assertRaisesMessage(RhOperationError, "Le salaire de base ne peut pas etre negatif."):
            create_employe(
                entreprise=self.entreprise_a,
                matricule="RH-003",
                nom="Lemba",
                prenom="Junior",
                poste=poste,
                date_embauche=date(2026, 1, 10),
                salaire_base=Decimal("-1.00"),
                utilisateur=self.owner_a,
            )

    def test_duplicate_matricule_same_entreprise_is_rejected(self):
        self._create_employe(matricule="RH-004")

        with self.assertRaisesMessage(RhOperationError, "Un employe avec ce matricule existe deja"):
            self._create_employe(matricule="RH-004", nom="Autre")

    def test_same_matricule_allowed_in_two_enterprises(self):
        employe_a = self._create_employe(entreprise=self.entreprise_a, matricule="RH-005")
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-005")

        self.assertNotEqual(employe_a.entreprise_id, employe_b.entreprise_id)

    def test_entreprise_a_does_not_see_entreprise_b_employes(self):
        employe_a = self._create_employe(entreprise=self.entreprise_a, matricule="RH-006")
        self._create_employe(entreprise=self.entreprise_b, matricule="RH-007")

        employes = list(get_employes_by_entreprise(self.entreprise_a))

        self.assertEqual(employes, [employe_a])

    def test_entreprise_a_cannot_modify_entreprise_b_employe(self):
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-008")

        self.client.force_login(self.owner_a)
        response = self.client.post(
            reverse("rh_employe_update", args=[employe_b.id]),
            {
                "matricule": "RH-008",
                "nom": "Change",
                "prenom": "Interdit",
                "poste": "",
                "type_contrat": Employe.TypeContrat.CDI,
                "date_embauche": "2026-01-10",
                "salaire_base": "100.00",
                "statut": Employe.Statut.ACTIF,
                "actif": "on",
            },
        )

        self.assertEqual(response.status_code, 404)

    def test_record_presence_valid(self):
        employe = self._create_employe(matricule="RH-009")

        presence = record_presence(
            entreprise=self.entreprise_a,
            employe=employe,
            date=date(2026, 1, 11),
            statut=Presence.Statut.PRESENT,
            utilisateur=self.owner_a,
        )

        self.assertEqual(presence.entreprise, self.entreprise_a)
        self.assertEqual(presence.employe, employe)
        self.assertEqual(presence.statut, Presence.Statut.PRESENT)

    def test_record_presence_rejects_unknown_status(self):
        employe = self._create_employe(matricule="RH-010")

        with self.assertRaisesMessage(RhOperationError, "Le statut de presence est invalide."):
            record_presence(
                entreprise=self.entreprise_a,
                employe=employe,
                date=date(2026, 1, 11),
                statut="teletravail",
                utilisateur=self.owner_a,
            )

    def test_record_presence_rejects_foreign_employee(self):
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-011")

        with self.assertRaisesMessage(RhOperationError, "L'employe selectionne appartient a une autre entreprise."):
            record_presence(
                entreprise=self.entreprise_a,
                employe=employe_b,
                date=date(2026, 1, 11),
                statut=Presence.Statut.PRESENT,
                utilisateur=self.owner_a,
            )

    def test_rh_access_denied_if_module_not_included(self):
        entreprise = create_entreprise("Entreprise Starter RH")
        owner = create_user("owner-rh-starter", "proprietaire", entreprise)
        starter_plan = Abonnement.objects.create(
            nom="Starter RH",
            code="starter",
            prix=19,
            duree_jours=30,
            actif=True,
            modules_inclus=["dashboard"],
        )
        activate_subscription_for_entreprise(entreprise=entreprise, plan=starter_plan, utilisateur=owner)

        self.client.force_login(owner)
        response = self.client.get(reverse("rh_employe_list"))

        self.assertRedirects(
            response,
            reverse("abonnement_expire") + "?module=rh&reason=premium_required",
        )

    def test_rh_access_allowed_if_module_included(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_employe_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Employes")

    def test_navigation_shows_rh_only_with_access(self):
        self.client.force_login(self.owner_a)
        premium_response = self.client.get(reverse("admin_dashboard"))
        premium_labels = [item["label"] for item in premium_response.context["dashboard_navigation"]]

        entreprise = create_entreprise("Entreprise Starter Nav RH")
        owner = create_user("owner-rh-starter-nav", "proprietaire", entreprise)
        starter_plan = Abonnement.objects.create(
            nom="Starter Nav RH",
            code="starter",
            prix=19,
            duree_jours=30,
            actif=True,
            modules_inclus=["dashboard"],
        )
        activate_subscription_for_entreprise(entreprise=entreprise, plan=starter_plan, utilisateur=owner)

        self.client.force_login(owner)
        starter_response = self.client.get(reverse("admin_dashboard"))
        starter_labels = [item["label"] for item in starter_response.context["dashboard_navigation"]]

        self.assertIn("Ressources humaines", premium_labels)
        self.assertNotIn("Ressources humaines", starter_labels)
