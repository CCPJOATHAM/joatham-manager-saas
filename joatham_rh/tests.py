import re
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils.html import strip_tags

from core.models import ActivityLog
from core.services.product_policy import can_access_module
from core.services.subscription import (
    PREMIUM_PLAN_CODE,
    activate_subscription_for_entreprise,
    get_default_paid_plans,
)
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement, User

from .models import DemandeConge, DocumentRH, Employe, Presence
from .selectors.rh import (
    get_conges_by_entreprise,
    get_documents_by_entreprise,
    get_employes_by_entreprise,
    get_rh_report_snapshot,
)
from .services.rh import (
    RhOperationError,
    approve_conge,
    create_conge,
    create_document_rh,
    create_employe,
    create_poste,
    record_presence,
    update_employe,
)


class RhFoundationTests(TestCase):
    def setUp(self):
        self.entreprise_a = create_entreprise("Entreprise RH A")
        self.entreprise_b = create_entreprise("Entreprise RH B")
        self.entreprise_a.raison_sociale = "CYBER CENTRE ET PAPETERIE JOATHAM"
        self.entreprise_a.rccm = "RCCM-123"
        self.entreprise_a.id_nat = "IDN-456"
        self.entreprise_a.numero_impot = "NIF-789"
        self.entreprise_a.adresse = "Avenue WOLA KITOKO"
        self.entreprise_a.ville = "Matadi"
        self.entreprise_a.pays = "RDC"
        self.entreprise_a.telephone = "+243970258117"
        self.entreprise_a.email = "contact@joatham.test"
        self.entreprise_a.save(
            update_fields=[
                "raison_sociale",
                "rccm",
                "id_nat",
                "numero_impot",
                "adresse",
                "ville",
                "pays",
                "telephone",
                "email",
            ]
        )
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

    def _assert_print_company_identity(self, response):
        self.assertContains(response, "CYBER CENTRE ET PAPETERIE JOATHAM")
        self.assertContains(response, "RCCM : RCCM-123")
        self.assertContains(response, "ID Nat : IDN-456")
        self.assertContains(response, "Numero impot : NIF-789")
        self.assertContains(response, "Avenue WOLA KITOKO")
        self.assertContains(response, "Matadi")
        self.assertContains(response, "RDC")
        self.assertContains(response, "+243970258117")
        self.assertContains(response, "contact@joatham.test")
        self.assertNotContains(response, "JOATHAM Manager")

    def _assert_no_figma_dummy_content(self, response):
        html = response.content.decode(response.charset or "utf-8", errors="replace")
        html_without_styles = re.sub(
            r"<style\b[^>]*>.*?</style>",
            "",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        visible_text = strip_tags(html_without_styles)
        figma_dummy_values = [
            "247",
            "234",
            "Marie Kouassi",
            "Jean Koffi",
            "Awa Diallo",
            "Kofi Mensah",
            "Amina Ndiaye",
            "Kwame Asante",
            "Fatou Sow",
            "Satisfaction 4.6/5",
            "Version 2.0",
        ]
        for value in figma_dummy_values:
            self.assertNotIn(value, visible_text)

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
        self.assertIsNone(employe.user)

    def test_user_can_exist_without_rh_employee(self):
        user = create_user("standalone-user-rh", User.Role.GESTIONNAIRE, self.entreprise_a)

        with self.assertRaises(Employe.DoesNotExist):
            user.rh_employe

    def test_create_employe_with_same_company_user_link(self):
        user = create_user("linked-user-rh", User.Role.GESTIONNAIRE, self.entreprise_a)
        poste = self._create_poste(nom="Caissier")

        employe = create_employe(
            entreprise=self.entreprise_a,
            matricule="RH-L001",
            nom="Liaison",
            prenom="Compte",
            poste=poste,
            date_embauche=date(2026, 1, 10),
            user=user,
            utilisateur=self.owner_a,
        )

        user.refresh_from_db()
        self.assertEqual(employe.user, user)
        self.assertEqual(user.rh_employe, employe)
        self.assertTrue(ActivityLog.objects.filter(action="employe_user_lie", objet_id=employe.id).exists())

    def test_create_employe_rejects_cross_tenant_user_link(self):
        poste = self._create_poste(nom="Assistant")

        with self.assertRaisesMessage(RhOperationError, "Le compte utilisateur selectionne appartient a une autre entreprise."):
            create_employe(
                entreprise=self.entreprise_a,
                matricule="RH-L002",
                nom="Cross",
                prenom="Tenant",
                poste=poste,
                date_embauche=date(2026, 1, 10),
                user=self.owner_b,
                utilisateur=self.owner_a,
            )

        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise_a,
                action="tentative_liaison_cross_tenant_bloquee",
            ).exists()
        )

    def test_create_employe_rejects_super_admin_user_link(self):
        super_admin = create_user("super-admin-rh-link", User.Role.SUPER_ADMIN, None)
        poste = self._create_poste(nom="Supervision")

        with self.assertRaisesMessage(RhOperationError, "Un super admin ne peut pas etre lie a un employe d'entreprise."):
            create_employe(
                entreprise=self.entreprise_a,
                matricule="RH-L003",
                nom="Super",
                prenom="Admin",
                poste=poste,
                date_embauche=date(2026, 1, 10),
                user=super_admin,
                utilisateur=self.owner_a,
            )

        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise_a,
                action="tentative_liaison_super_admin_bloquee",
            ).exists()
        )

    def test_create_employe_rejects_user_already_linked_to_another_employee(self):
        user = create_user("already-linked-rh", User.Role.COMPTABLE, self.entreprise_a)
        self._create_employe(matricule="RH-L004", nom="Premier")

        Employe.objects.filter(matricule="RH-L004").update(user=user)
        poste = self._create_poste(nom="Controle")

        with self.assertRaisesMessage(RhOperationError, "Ce compte utilisateur est deja lie a un autre employe RH."):
            create_employe(
                entreprise=self.entreprise_a,
                matricule="RH-L005",
                nom="Second",
                prenom="Lien",
                poste=poste,
                date_embauche=date(2026, 1, 10),
                user=user,
                utilisateur=self.owner_a,
            )

    def test_manager_cannot_link_user_account_in_service(self):
        user = create_user("manager-service-link-rh", User.Role.GESTIONNAIRE, self.entreprise_a)

        with self.assertRaisesMessage(RhOperationError, "Seul le proprietaire peut modifier la liaison avec un compte utilisateur."):
            create_employe(
                entreprise=self.entreprise_a,
                matricule="RH-L009",
                nom="Manager",
                prenom="Lien",
                date_embauche=date(2026, 1, 10),
                user=user,
                utilisateur=self.manager_a,
            )

        self.assertFalse(Employe.objects.filter(matricule="RH-L009").exists())

    def test_remove_user_link_keeps_employee_and_user(self):
        user = create_user("unlink-user-rh", User.Role.COMPTABLE, self.entreprise_a)
        employe = create_employe(
            entreprise=self.entreprise_a,
            matricule="RH-L006",
            nom="Delier",
            prenom="Compte",
            date_embauche=date(2026, 1, 10),
            user=user,
            utilisateur=self.owner_a,
        )

        updated = update_employe(
            entreprise=self.entreprise_a,
            employe=employe,
            matricule=employe.matricule,
            nom=employe.nom,
            prenom=employe.prenom,
            date_embauche=employe.date_embauche,
            poste=employe.poste,
            type_contrat=employe.type_contrat,
            salaire_base=employe.salaire_base,
            statut=employe.statut,
            actif=employe.actif,
            user=None,
            utilisateur=self.owner_a,
        )

        self.assertIsNone(updated.user)
        self.assertTrue(Employe.objects.filter(id=employe.id).exists())
        self.assertTrue(User.objects.filter(id=user.id).exists())
        self.assertTrue(ActivityLog.objects.filter(action="employe_user_delie", objet_id=employe.id).exists())

    def test_inactive_user_can_remain_linked_to_employee(self):
        user = create_user("inactive-linked-rh", User.Role.GESTIONNAIRE, self.entreprise_a)
        employe = create_employe(
            entreprise=self.entreprise_a,
            matricule="RH-L007",
            nom="Compte",
            prenom="Inactif",
            date_embauche=date(2026, 1, 10),
            user=user,
            utilisateur=self.owner_a,
        )

        user.is_active = False
        user.save(update_fields=["is_active"])

        employe.refresh_from_db()
        self.assertEqual(employe.user, user)

    def test_changing_poste_does_not_change_access_role(self):
        user = create_user("role-stable-rh", User.Role.GESTIONNAIRE, self.entreprise_a)
        poste_initial = self._create_poste(nom="Agent")
        poste_nouveau = self._create_poste(nom="Comptable interne")
        employe = create_employe(
            entreprise=self.entreprise_a,
            matricule="RH-L008",
            nom="Role",
            prenom="Stable",
            poste=poste_initial,
            date_embauche=date(2026, 1, 10),
            user=user,
            utilisateur=self.owner_a,
        )

        update_employe(
            entreprise=self.entreprise_a,
            employe=employe,
            matricule=employe.matricule,
            nom=employe.nom,
            prenom=employe.prenom,
            date_embauche=employe.date_embauche,
            poste=poste_nouveau,
            type_contrat=employe.type_contrat,
            salaire_base=employe.salaire_base,
            statut=employe.statut,
            actif=employe.actif,
            user=user,
            utilisateur=self.owner_a,
        )

        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.GESTIONNAIRE)

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
        self.assertContains(response, "Poste RH")

    def test_owner_form_can_link_user_account(self):
        user = create_user("form-link-rh", User.Role.GESTIONNAIRE, self.entreprise_a)
        poste = self._create_poste(nom="Formateur")

        self.client.force_login(self.owner_a)
        response = self.client.post(
            reverse("rh_employe_create"),
            {
                "matricule": "RH-F001",
                "nom": "Form",
                "prenom": "Link",
                "sexe": "",
                "telephone": "",
                "email": "",
                "adresse": "",
                "user": str(user.id),
                "poste": str(poste.id),
                "type_contrat": Employe.TypeContrat.CDI,
                "date_embauche": "2026-01-10",
                "salaire_base": "150.00",
                "statut": Employe.Statut.ACTIF,
                "actif": "on",
            },
        )

        employe = Employe.objects.get(matricule="RH-F001")
        self.assertRedirects(response, reverse("rh_employe_detail", args=[employe.id]))
        self.assertEqual(employe.user, user)

    def test_manager_update_cannot_change_user_link(self):
        linked_user = create_user("manager-link-kept", User.Role.GESTIONNAIRE, self.entreprise_a)
        malicious_user = create_user("manager-link-malicious", User.Role.COMPTABLE, self.entreprise_a)
        employe = create_employe(
            entreprise=self.entreprise_a,
            matricule="RH-F002",
            nom="Lien",
            prenom="Protege",
            date_embauche=date(2026, 1, 10),
            user=linked_user,
            utilisateur=self.owner_a,
        )

        self.client.force_login(self.manager_a)
        response = self.client.post(
            reverse("rh_employe_update", args=[employe.id]),
            {
                "matricule": employe.matricule,
                "nom": "Lien",
                "prenom": "Protege",
                "sexe": "",
                "telephone": "",
                "email": "",
                "adresse": "",
                "user": str(malicious_user.id),
                "poste": "",
                "type_contrat": employe.type_contrat,
                "date_embauche": "2026-01-10",
                "salaire_base": "",
                "statut": employe.statut,
                "actif": "on",
            },
        )

        self.assertRedirects(response, reverse("rh_employe_detail", args=[employe.id]))
        employe.refresh_from_db()
        self.assertEqual(employe.user, linked_user)

    def test_employee_detail_displays_linked_user_account(self):
        user = create_user("detail-link-rh", User.Role.COMPTABLE, self.entreprise_a)
        employe = create_employe(
            entreprise=self.entreprise_a,
            matricule="RH-F003",
            nom="Detail",
            prenom="Compte",
            date_embauche=date(2026, 1, 10),
            user=user,
            utilisateur=self.owner_a,
        )

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_employe_detail", args=[employe.id]))

        self.assertContains(response, "Compte utilisateur lie")
        self.assertContains(response, user.username)
        self.assertContains(response, "Comptable")

    def test_employee_detail_displays_no_linked_user_state(self):
        employe = self._create_employe(matricule="RH-F004", nom="SansCompte")

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_employe_detail", args=[employe.id]))

        self.assertContains(response, "Compte utilisateur lie")
        self.assertContains(response, "Aucun compte utilisateur lie.")

    def test_employee_list_displays_user_link_badges(self):
        user = create_user("list-link-rh", User.Role.GESTIONNAIRE, self.entreprise_a)
        create_employe(
            entreprise=self.entreprise_a,
            matricule="RH-F005",
            nom="Liste",
            prenom="Lie",
            date_embauche=date(2026, 1, 10),
            user=user,
            utilisateur=self.owner_a,
        )
        self._create_employe(matricule="RH-F006", nom="ListeSansCompte")

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_employe_list"))

        self.assertContains(response, "Compte utilisateur")
        self.assertContains(response, "Lie")
        self.assertContains(response, "Non lie")

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

    def test_create_conge_valid(self):
        employe = self._create_employe(matricule="RH-C001")

        conge = create_conge(
            entreprise=self.entreprise_a,
            employe=employe,
            type_conge=DemandeConge.TypeConge.ANNUEL,
            date_debut=date(2026, 5, 4),
            date_fin=date(2026, 5, 8),
            motif="Repos annuel",
            utilisateur=self.owner_a,
        )

        self.assertEqual(conge.entreprise, self.entreprise_a)
        self.assertEqual(conge.employe, employe)
        self.assertEqual(conge.statut, DemandeConge.Statut.EN_ATTENTE)

    def test_create_conge_rejects_end_before_start(self):
        employe = self._create_employe(matricule="RH-C002")

        with self.assertRaisesMessage(RhOperationError, "La date de fin doit etre superieure ou egale"):
            create_conge(
                entreprise=self.entreprise_a,
                employe=employe,
                type_conge=DemandeConge.TypeConge.ANNUEL,
                date_debut=date(2026, 5, 8),
                date_fin=date(2026, 5, 4),
                utilisateur=self.owner_a,
            )

    def test_create_conge_rejects_foreign_employee(self):
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-C003")

        with self.assertRaisesMessage(RhOperationError, "L'employe selectionne appartient a une autre entreprise."):
            create_conge(
                entreprise=self.entreprise_a,
                employe=employe_b,
                type_conge=DemandeConge.TypeConge.MALADIE,
                date_debut=date(2026, 5, 4),
                date_fin=date(2026, 5, 5),
                utilisateur=self.owner_a,
            )

    def test_approve_conge_valid(self):
        employe = self._create_employe(matricule="RH-C004")
        conge = create_conge(
            entreprise=self.entreprise_a,
            employe=employe,
            type_conge=DemandeConge.TypeConge.EXCEPTIONNEL,
            date_debut=date(2026, 5, 4),
            date_fin=date(2026, 5, 4),
            utilisateur=self.owner_a,
        )

        approved = approve_conge(entreprise=self.entreprise_a, conge=conge, decide_par=self.manager_a)

        self.assertEqual(approved.statut, DemandeConge.Statut.APPROUVE)
        self.assertEqual(approved.approuve_par, self.manager_a)
        self.assertIsNotNone(approved.date_decision)

    def test_create_conge_rejects_unknown_status(self):
        employe = self._create_employe(matricule="RH-C005")

        with self.assertRaisesMessage(RhOperationError, "Le statut de conge est invalide."):
            create_conge(
                entreprise=self.entreprise_a,
                employe=employe,
                type_conge=DemandeConge.TypeConge.AUTRE,
                date_debut=date(2026, 5, 4),
                date_fin=date(2026, 5, 5),
                statut="a_verifier",
                utilisateur=self.owner_a,
            )

    def test_conge_selector_is_scoped_to_entreprise(self):
        employe_a = self._create_employe(entreprise=self.entreprise_a, matricule="RH-C006")
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-C007")
        conge_a = create_conge(
            entreprise=self.entreprise_a,
            employe=employe_a,
            type_conge=DemandeConge.TypeConge.ANNUEL,
            date_debut=date(2026, 5, 4),
            date_fin=date(2026, 5, 5),
            utilisateur=self.owner_a,
        )
        create_conge(
            entreprise=self.entreprise_b,
            employe=employe_b,
            type_conge=DemandeConge.TypeConge.ANNUEL,
            date_debut=date(2026, 5, 4),
            date_fin=date(2026, 5, 5),
            utilisateur=self.owner_b,
        )

        self.assertEqual(list(get_conges_by_entreprise(self.entreprise_a)), [conge_a])

    def test_create_document_rh_valid(self):
        employe = self._create_employe(matricule="RH-D001")

        document = create_document_rh(
            entreprise=self.entreprise_a,
            employe=employe,
            type_document=DocumentRH.TypeDocument.CONTRAT,
            titre="Contrat de travail",
            description="Reference interne",
            date_document=date(2026, 5, 1),
            utilisateur=self.owner_a,
        )

        self.assertEqual(document.entreprise, self.entreprise_a)
        self.assertEqual(document.employe, employe)
        self.assertEqual(document.titre, "Contrat de travail")

    def test_create_document_rh_requires_title(self):
        employe = self._create_employe(matricule="RH-D002")

        with self.assertRaisesMessage(RhOperationError, "Le titre du document est obligatoire."):
            create_document_rh(
                entreprise=self.entreprise_a,
                employe=employe,
                type_document=DocumentRH.TypeDocument.ATTESTATION,
                titre="",
                utilisateur=self.owner_a,
            )

    def test_create_document_rh_rejects_foreign_employee(self):
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-D003")

        with self.assertRaisesMessage(RhOperationError, "L'employe selectionne appartient a une autre entreprise."):
            create_document_rh(
                entreprise=self.entreprise_a,
                employe=employe_b,
                type_document=DocumentRH.TypeDocument.CERTIFICAT,
                titre="Certificat medical",
                utilisateur=self.owner_a,
            )

    def test_document_selector_is_scoped_to_entreprise(self):
        employe_a = self._create_employe(entreprise=self.entreprise_a, matricule="RH-D004")
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-D005")
        document_a = create_document_rh(
            entreprise=self.entreprise_a,
            employe=employe_a,
            type_document=DocumentRH.TypeDocument.CONTRAT,
            titre="Contrat A",
            utilisateur=self.owner_a,
        )
        create_document_rh(
            entreprise=self.entreprise_b,
            employe=employe_b,
            type_document=DocumentRH.TypeDocument.CONTRAT,
            titre="Contrat B",
            utilisateur=self.owner_b,
        )

        self.assertEqual(list(get_documents_by_entreprise(self.entreprise_a)), [document_a])

    def test_rh_reports_are_scoped_to_entreprise(self):
        employe_a = self._create_employe(entreprise=self.entreprise_a, matricule="RH-R001")
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-R002")
        record_presence(
            entreprise=self.entreprise_a,
            employe=employe_a,
            date=date(2026, 5, 6),
            statut=Presence.Statut.PRESENT,
            utilisateur=self.owner_a,
        )
        record_presence(
            entreprise=self.entreprise_b,
            employe=employe_b,
            date=date(2026, 5, 6),
            statut=Presence.Statut.ABSENT,
            utilisateur=self.owner_b,
        )
        conge_a = create_conge(
            entreprise=self.entreprise_a,
            employe=employe_a,
            type_conge=DemandeConge.TypeConge.ANNUEL,
            date_debut=date(2026, 5, 7),
            date_fin=date(2026, 5, 8),
            utilisateur=self.owner_a,
        )
        approve_conge(entreprise=self.entreprise_a, conge=conge_a, decide_par=self.manager_a)
        create_conge(
            entreprise=self.entreprise_b,
            employe=employe_b,
            type_conge=DemandeConge.TypeConge.MALADIE,
            date_debut=date(2026, 5, 7),
            date_fin=date(2026, 5, 8),
            utilisateur=self.owner_b,
        )

        report = get_rh_report_snapshot(self.entreprise_a, as_of=date(2026, 5, 19))

        self.assertEqual(report["total_employes"], 1)
        self.assertEqual(report["presences_mois"], 1)
        self.assertEqual(report["absences_mois"], 0)
        self.assertEqual(report["conges_approuves"], 1)
        self.assertEqual(report["conges_en_attente"], 0)

    def test_rh_reports_access_denied_without_module(self):
        entreprise = create_entreprise("Entreprise Starter Reports RH")
        owner = create_user("owner-rh-reports-starter", "proprietaire", entreprise)
        starter_plan = Abonnement.objects.create(
            nom="Starter Reports RH",
            code="starter",
            prix=19,
            duree_jours=30,
            actif=True,
            modules_inclus=["dashboard"],
        )
        activate_subscription_for_entreprise(entreprise=entreprise, plan=starter_plan, utilisateur=owner)

        self.client.force_login(owner)
        response = self.client.get(reverse("rh_reports"))

        self.assertRedirects(
            response,
            reverse("abonnement_expire") + "?module=rh&reason=premium_required",
        )

    def test_rh_reports_access_allowed_with_premium(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_reports"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tableau de bord RH")
        self.assertContains(response, "Rapports RH")

    def test_rh_navigation_contains_phase8_entries_when_module_is_active(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_employe_list"))

        self.assertContains(response, "Tableau de bord")
        self.assertContains(response, "Postes RH")
        self.assertContains(response, "Conges")
        self.assertContains(response, "Documents")
        self.assertContains(response, "Rapports")
        self.assertContains(response, "Exports")
        self.assertContains(response, "Impressions")

    def test_rh_sidebar_toggle_assets_are_rendered(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_reports"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="rh-sidebar"')
        self.assertContains(response, 'id="rh-sidebar-toggle"')
        self.assertContains(response, 'aria-controls="rh-sidebar"')
        self.assertContains(response, "rh-sidebar-collapsed")
        self.assertContains(response, 'addEventListener("click"')

    def test_rh_dashboard_uses_real_data_without_figma_placeholders(self):
        employe = self._create_employe(matricule="RH-UI001", nom="DesignReel")
        record_presence(
            entreprise=self.entreprise_a,
            employe=employe,
            date=date(2026, 5, 20),
            statut=Presence.Statut.PRESENT,
            utilisateur=self.owner_a,
        )
        create_conge(
            entreprise=self.entreprise_a,
            employe=employe,
            type_conge=DemandeConge.TypeConge.ANNUEL,
            date_debut=date(2026, 5, 21),
            date_fin=date(2026, 5, 22),
            utilisateur=self.owner_a,
        )
        create_document_rh(
            entreprise=self.entreprise_a,
            employe=employe,
            type_document=DocumentRH.TypeDocument.CONTRAT,
            titre="Contrat design premium",
            utilisateur=self.owner_a,
        )

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_reports"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tableau de bord RH")
        self.assertContains(response, "Activite recente")
        self.assertContains(response, "Employes recents")
        self.assertContains(response, "RH-UI001")
        self.assertContains(response, "DesignReel")
        self.assertContains(response, "Contrat design premium")
        self.assertContains(response, reverse("rh_reports_export_csv"))
        self.assertContains(response, reverse("rh_reports_print"))
        self._assert_no_figma_dummy_content(response)

    def test_employe_export_csv_allowed_with_rh_module(self):
        employe = self._create_employe(matricule="RH-X001", nom="Export")

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_employe_export_csv"))
        content = response.content.decode("utf-8-sig")

        self.assertEqual(response.status_code, 200)
        self.assertIn("joatham-rh-employes.csv", response["Content-Disposition"])
        self.assertIn(employe.matricule, content)
        self.assertIn("Export", content)

    def test_employe_export_csv_denied_without_rh_module(self):
        entreprise = create_entreprise("Entreprise Starter Export RH")
        owner = create_user("owner-rh-export-starter", "proprietaire", entreprise)
        starter_plan = Abonnement.objects.create(
            nom="Starter Export RH",
            code="starter",
            prix=19,
            duree_jours=30,
            actif=True,
            modules_inclus=["dashboard"],
        )
        activate_subscription_for_entreprise(entreprise=entreprise, plan=starter_plan, utilisateur=owner)

        self.client.force_login(owner)
        response = self.client.get(reverse("rh_employe_export_csv"))

        self.assertRedirects(
            response,
            reverse("abonnement_expire") + "?module=rh&reason=premium_required",
        )

    def test_employe_export_csv_is_scoped_to_entreprise(self):
        employe_a = self._create_employe(entreprise=self.entreprise_a, matricule="RH-X002", nom="AlphaExport")
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-X003", nom="BetaExport")

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_employe_export_csv"))
        content = response.content.decode("utf-8-sig")

        self.assertIn(employe_a.matricule, content)
        self.assertNotIn(employe_b.matricule, content)
        self.assertNotIn("BetaExport", content)

    def test_presence_export_csv_is_scoped_to_entreprise(self):
        employe_a = self._create_employe(entreprise=self.entreprise_a, matricule="RH-X004")
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-X005")
        record_presence(
            entreprise=self.entreprise_a,
            employe=employe_a,
            date=date(2026, 5, 8),
            statut=Presence.Statut.PRESENT,
            utilisateur=self.owner_a,
        )
        record_presence(
            entreprise=self.entreprise_b,
            employe=employe_b,
            date=date(2026, 5, 8),
            statut=Presence.Statut.ABSENT,
            utilisateur=self.owner_b,
        )

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_presence_export_csv"))
        content = response.content.decode("utf-8-sig")

        self.assertIn(employe_a.matricule, content)
        self.assertNotIn(employe_b.matricule, content)

    def test_conge_export_csv_is_scoped_to_entreprise(self):
        employe_a = self._create_employe(entreprise=self.entreprise_a, matricule="RH-X006")
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-X007")
        create_conge(
            entreprise=self.entreprise_a,
            employe=employe_a,
            type_conge=DemandeConge.TypeConge.ANNUEL,
            date_debut=date(2026, 5, 10),
            date_fin=date(2026, 5, 12),
            utilisateur=self.owner_a,
        )
        create_conge(
            entreprise=self.entreprise_b,
            employe=employe_b,
            type_conge=DemandeConge.TypeConge.MALADIE,
            date_debut=date(2026, 5, 10),
            date_fin=date(2026, 5, 12),
            utilisateur=self.owner_b,
        )

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_conge_export_csv"))
        content = response.content.decode("utf-8-sig")

        self.assertIn(employe_a.matricule, content)
        self.assertNotIn(employe_b.matricule, content)

    def test_document_export_csv_is_scoped_to_entreprise(self):
        employe_a = self._create_employe(entreprise=self.entreprise_a, matricule="RH-X008")
        employe_b = self._create_employe(entreprise=self.entreprise_b, matricule="RH-X009")
        create_document_rh(
            entreprise=self.entreprise_a,
            employe=employe_a,
            type_document=DocumentRH.TypeDocument.CONTRAT,
            titre="Document Alpha",
            utilisateur=self.owner_a,
        )
        create_document_rh(
            entreprise=self.entreprise_b,
            employe=employe_b,
            type_document=DocumentRH.TypeDocument.CONTRAT,
            titre="Document Beta",
            utilisateur=self.owner_b,
        )

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_document_export_csv"))
        content = response.content.decode("utf-8-sig")

        self.assertIn("Document Alpha", content)
        self.assertNotIn("Document Beta", content)

    def test_rh_report_export_csv_contains_correct_data(self):
        employe = self._create_employe(matricule="RH-X010")
        record_presence(
            entreprise=self.entreprise_a,
            employe=employe,
            date=date(2026, 5, 8),
            statut=Presence.Statut.PRESENT,
            utilisateur=self.owner_a,
        )

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_reports_export_csv"))
        content = response.content.decode("utf-8-sig")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Total employes,1", content)
        self.assertIn("Presences du mois,1", content)

    def test_employe_list_filters_by_status_and_poste(self):
        poste_a = self._create_poste(nom="Poste filtre actif")
        poste_b = self._create_poste(nom="Poste filtre suspendu")
        employe_a = create_employe(
            entreprise=self.entreprise_a,
            matricule="RH-F001",
            nom="FiltreActif",
            prenom="Junior",
            poste=poste_a,
            date_embauche=date(2026, 1, 10),
            statut=Employe.Statut.ACTIF,
            utilisateur=self.owner_a,
        )
        employe_b = create_employe(
            entreprise=self.entreprise_a,
            matricule="RH-F002",
            nom="FiltreSuspendu",
            prenom="Junior",
            poste=poste_b,
            date_embauche=date(2026, 1, 10),
            statut=Employe.Statut.SUSPENDU,
            utilisateur=self.owner_a,
        )

        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("rh_employe_list"),
            {"statut": Employe.Statut.ACTIF, "poste": str(poste_a.id), "q": "Filtre"},
        )

        self.assertContains(response, employe_a.matricule)
        self.assertNotContains(response, employe_b.matricule)

    def test_conge_list_filters_by_status_and_type(self):
        employe = self._create_employe(matricule="RH-F003")
        other_employe = self._create_employe(matricule="RH-F004")
        approved = create_conge(
            entreprise=self.entreprise_a,
            employe=employe,
            type_conge=DemandeConge.TypeConge.ANNUEL,
            date_debut=date(2026, 5, 10),
            date_fin=date(2026, 5, 12),
            utilisateur=self.owner_a,
        )
        approve_conge(entreprise=self.entreprise_a, conge=approved, decide_par=self.manager_a)
        pending = create_conge(
            entreprise=self.entreprise_a,
            employe=other_employe,
            type_conge=DemandeConge.TypeConge.MALADIE,
            date_debut=date(2026, 6, 10),
            date_fin=date(2026, 6, 12),
            utilisateur=self.owner_a,
        )

        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("rh_conge_list"),
            {"statut": DemandeConge.Statut.APPROUVE, "type_conge": DemandeConge.TypeConge.ANNUEL},
        )

        self.assertContains(response, "Annuel")
        self.assertContains(response, approved.employe.matricule)
        self.assertNotContains(response, pending.employe.matricule)

    def test_employe_print_view_is_available(self):
        employe = self._create_employe(matricule="RH-P001")

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_employe_print", args=[employe.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fiche employe")
        self.assertContains(response, employe.matricule)
        self._assert_print_company_identity(response)

    def test_employe_list_print_uses_company_identity(self):
        self._create_employe(matricule="RH-P002")

        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_employe_list_print"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Liste employes")
        self._assert_print_company_identity(response)

    def test_rh_reports_print_uses_company_identity(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("rh_reports_print"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rapport RH synthetique")
        self._assert_print_company_identity(response)

    def test_rh_pages_show_export_and_print_links_when_authorized(self):
        self.client.force_login(self.owner_a)
        employee_response = self.client.get(reverse("rh_employe_list"))
        report_response = self.client.get(reverse("rh_reports"))

        self.assertContains(employee_response, reverse("rh_employe_export_csv"))
        self.assertContains(employee_response, reverse("rh_employe_list_print"))
        self.assertContains(report_response, reverse("rh_reports_export_csv"))
        self.assertContains(report_response, reverse("rh_reports_print"))
