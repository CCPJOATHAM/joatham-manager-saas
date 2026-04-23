from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import TestCase
from django.urls import reverse

from datetime import date
from decimal import Decimal

from joatham_billing.models import PaiementFacture
from joatham_billing.services.facturation import register_payment
from joatham_billing.tests.factories import create_client, create_entreprise, create_facture_sample, create_user
from joatham_clients.services.clients_service import create_client_for_entreprise
from joatham_users.models import Abonnement, AbonnementEntreprise, User

from .models import ActivityLog, PaiementAbonnement
from .selectors.audit import (
    get_activity_actions_for_entreprise,
    get_activity_logs_by_entreprise,
    get_activity_modules_for_entreprise,
    get_inscription_billing_history,
    get_activity_roles_for_entreprise,
    get_activity_users_for_entreprise,
)
from .services.tenancy import get_object_for_entreprise, get_user_entreprise_or_raise, scope_queryset_to_entreprise
from .services.subscription import (
    create_subscription_payment_request,
    refuse_subscription_payment,
    validate_subscription_payment,
)
from joatham_users.permissions import user_has_permission


class TenancyServiceTests(TestCase):
    def setUp(self):
        self.entreprise_a = create_entreprise("Entreprise A")
        self.entreprise_b = create_entreprise("Entreprise B")
        self.user_a = create_user("tenant-a", "proprietaire", self.entreprise_a)
        self.client_a = create_client(self.entreprise_a, "Client A")
        self.client_b = create_client(self.entreprise_b, "Client B")

    def test_get_user_entreprise_or_raise_returns_bound_entreprise(self):
        self.assertEqual(get_user_entreprise_or_raise(self.user_a), self.entreprise_a)

    def test_get_user_entreprise_or_raise_rejects_missing_tenant(self):
        user_without_company = create_user("tenant-none", "gestionnaire", self.entreprise_a)
        user_without_company.entreprise = None
        user_without_company.save(update_fields=["entreprise"])

        with self.assertRaises(PermissionDenied):
            get_user_entreprise_or_raise(user_without_company)

    def test_get_user_entreprise_or_raise_rejects_super_admin_platform_user(self):
        super_admin = create_user("platform-admin", "super_admin", self.entreprise_a)

        with self.assertRaises(PermissionDenied):
            get_user_entreprise_or_raise(super_admin)

    def test_super_admin_permissions_remain_platform_only(self):
        super_admin = create_user("platform-root", "super_admin", self.entreprise_a)
        super_admin.is_superuser = True
        super_admin.save(update_fields=["is_superuser"])

        self.assertTrue(user_has_permission(super_admin, "superadmin.view"))
        self.assertFalse(user_has_permission(super_admin, "clients.view"))

    def test_scope_queryset_to_entreprise_filters_cross_tenant_rows(self):
        scoped = scope_queryset_to_entreprise(self.client_a.__class__.objects.all(), self.entreprise_a)
        self.assertEqual(list(scoped), [self.client_a])

    def test_get_object_for_entreprise_prevents_cross_tenant_access(self):
        found = get_object_for_entreprise(self.client_a.__class__.objects.all(), self.entreprise_a, id=self.client_a.id)
        self.assertEqual(found, self.client_a)

        with self.assertRaises(Http404):
            get_object_for_entreprise(self.client_a.__class__.objects.all(), self.entreprise_a, id=self.client_b.id)


class AuditLogTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Audit")
        self.entreprise_b = create_entreprise("Entreprise Audit B")
        self.gestionnaire = create_user("gestion-audit", "gestionnaire", self.entreprise)
        self.comptable = create_user("compta-audit", "comptable", self.entreprise)
        self.client_metier = create_client(self.entreprise, "Client Audit")

    def test_facture_creation_creates_audit_event_scoped_to_entreprise_and_user(self):
        facture = create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("100"))

        audit = ActivityLog.objects.get(action="facture_creee", objet_id=facture.id)
        self.assertEqual(audit.entreprise, self.entreprise)
        self.assertEqual(audit.utilisateur, self.gestionnaire)
        self.assertEqual(audit.module, "billing")
        self.assertEqual(audit.objet_type, "Facture")

    def test_payment_registration_creates_audit_event_without_breaking_workflow(self):
        facture = create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("100"))

        paiement = register_payment(
            facture=facture,
            montant=Decimal("20"),
            mode=PaiementFacture.ModePaiement.ESPECES,
            user=self.comptable,
            note="Acompte audit",
        )

        audit = ActivityLog.objects.get(action="facture_payee", objet_id=paiement.id)
        self.assertEqual(audit.entreprise, self.entreprise)
        self.assertEqual(audit.utilisateur, self.comptable)
        self.assertEqual(audit.module, "billing")
        self.assertEqual(paiement.montant, Decimal("20"))

    def test_client_creation_creates_audit_event(self):
        client = create_client_for_entreprise(
            entreprise=self.entreprise,
            nom="Client Journalise",
            telephone="+243111111111",
            email="journalise@example.com",
            utilisateur=self.gestionnaire,
        )

        audit = ActivityLog.objects.get(action="client_cree", objet_id=client.id)
        self.assertEqual(audit.entreprise, self.entreprise)
        self.assertEqual(audit.utilisateur, self.gestionnaire)
        self.assertEqual(audit.module, "clients")

    def test_audit_log_is_isolated_by_entreprise(self):
        client_b = create_client(self.entreprise_b, "Client B")
        user_b = create_user("gestion-audit-b", "gestionnaire", self.entreprise_b)
        create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("50"))
        create_facture_sample(self.entreprise_b, user_b, client_b, Decimal("70"))

        logs_a = ActivityLog.objects.filter(entreprise=self.entreprise)
        logs_b = ActivityLog.objects.filter(entreprise=self.entreprise_b)
        self.assertTrue(logs_a.exists())
        self.assertTrue(logs_b.exists())
        self.assertTrue(all(log.entreprise_id == self.entreprise.id for log in logs_a))
        self.assertTrue(all(log.entreprise_id == self.entreprise_b.id for log in logs_b))

    def test_audit_selectors_support_filters_and_desc_order(self):
        facture = create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("90"))
        register_payment(
            facture=facture,
            montant=Decimal("10"),
            mode=PaiementFacture.ModePaiement.ESPECES,
            user=self.comptable,
            note="Paiement filtre",
        )

        logs = list(get_activity_logs_by_entreprise(self.entreprise))
        self.assertGreaterEqual(len(logs), 2)
        self.assertGreaterEqual(logs[0].id, logs[-1].id)
        self.assertTrue(all(log.entreprise_id == self.entreprise.id for log in logs))

        billing_logs = list(get_activity_logs_by_entreprise(self.entreprise, module="billing"))
        self.assertTrue(all(log.module == "billing" for log in billing_logs))

        comptable_logs = list(get_activity_logs_by_entreprise(self.entreprise, utilisateur_id=self.comptable.id))
        self.assertTrue(all(log.utilisateur_id == self.comptable.id for log in comptable_logs))

        payment_logs = list(get_activity_logs_by_entreprise(self.entreprise, action="facture_payee"))
        self.assertTrue(all(log.action == "facture_payee" for log in payment_logs))

        role_logs = list(get_activity_logs_by_entreprise(self.entreprise, role="comptable"))
        self.assertTrue(role_logs)
        self.assertTrue(all(log.utilisateur and log.utilisateur.role == "comptable" for log in role_logs))

        dated_logs = list(
            get_activity_logs_by_entreprise(
                self.entreprise,
                date_from=logs[-1].date_creation.date(),
                date_to=logs[0].date_creation.date(),
            )
        )
        self.assertTrue(dated_logs)

    def test_audit_filter_options_are_scoped_to_entreprise(self):
        create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("30"))
        client_b = create_client(self.entreprise_b, "Client B")
        user_b = create_user("gestion-audit-b2", "gestionnaire", self.entreprise_b)
        create_facture_sample(self.entreprise_b, user_b, client_b, Decimal("40"))

        self.assertIn("billing", get_activity_modules_for_entreprise(self.entreprise))
        self.assertIn("facture_creee", get_activity_actions_for_entreprise(self.entreprise))
        users = list(get_activity_users_for_entreprise(self.entreprise))
        self.assertIn(self.gestionnaire, users)
        self.assertNotIn(user_b, users)
        role_values = [item["value"] for item in get_activity_roles_for_entreprise(self.entreprise)]
        self.assertIn("gestionnaire", role_values)
        self.assertNotIn("proprietaire", role_values)

    def test_activity_log_view_is_restricted_to_proprietaire_and_comptable_only(self):
        create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("100"))

        self.client.force_login(self.gestionnaire)
        forbidden = self.client.get(reverse("activity_log_list"))
        self.assertEqual(forbidden.status_code, 403)

        proprietaire = create_user("owner-audit", "proprietaire", self.entreprise)
        self.client.force_login(proprietaire)
        allowed = self.client.get(reverse("activity_log_list"))
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "Controle des flux")

        self.client.force_login(self.comptable)
        comptable_allowed = self.client.get(reverse("activity_log_list"))
        self.assertEqual(comptable_allowed.status_code, 200)
        self.assertContains(comptable_allowed, "Controle des flux")

    def test_activity_log_view_filters_and_isolation_work(self):
        facture = create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("100"))
        register_payment(
            facture=facture,
            montant=Decimal("10"),
            mode=PaiementFacture.ModePaiement.ESPECES,
            user=self.comptable,
            note="Paiement vue",
        )
        client_b = create_client(self.entreprise_b, "Client Vue B")
        owner_b = create_user("owner-audit-b", "proprietaire", self.entreprise_b)
        create_facture_sample(self.entreprise_b, owner_b, client_b, Decimal("50"))

        proprietaire = create_user("owner-audit-view", "proprietaire", self.entreprise)
        self.client.force_login(proprietaire)

        response = self.client.get(reverse("activity_log_list"))
        self.assertEqual(response.status_code, 200)
        logs = list(response.context["logs"])
        self.assertTrue(all(log.entreprise_id == self.entreprise.id for log in logs))

        filtered = self.client.get(
            reverse("activity_log_list"),
            {
                "action": "facture_payee",
                "utilisateur": self.comptable.id,
                "module": "billing",
                "role": "comptable",
                "date_from": logs[-1].date_creation.date().isoformat(),
                "date_to": logs[0].date_creation.date().isoformat(),
            },
        )
        self.assertEqual(filtered.status_code, 200)
        filtered_logs = list(filtered.context["logs"])
        self.assertTrue(filtered_logs)
        self.assertTrue(all(log.action == "facture_payee" for log in filtered_logs))
        self.assertTrue(all(log.utilisateur_id == self.comptable.id for log in filtered_logs))
        self.assertTrue(all(log.module == "billing" for log in filtered_logs))
        self.assertTrue(all(log.utilisateur and log.utilisateur.role == "comptable" for log in filtered_logs))

    def test_get_inscription_billing_history_returns_logs_in_desc_order(self):
        from joatham_apprenants.models import Apprenant, Formation, InscriptionFormation

        apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Audit", prenom="Eleve")
        formation = Formation.objects.create(entreprise=self.entreprise, nom="Excel", prix=Decimal("100.00"))
        inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise,
            apprenant=apprenant,
            formation=formation,
            montant_prevu=Decimal("100.00"),
        )

        ActivityLog.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.gestionnaire,
            action="facture_inscription_creee",
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=inscription.id,
            description="Facture creee.",
            metadata={"facture_numero": "F-0001"},
        )
        ActivityLog.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.gestionnaire,
            action="facture_deliee_inscription",
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=inscription.id,
            description="Facture deliee.",
            metadata={"facture_numero": "F-0001"},
        )

        history = get_inscription_billing_history(inscription)
        self.assertEqual([entry["action"] for entry in history], ["facture_deliee_inscription", "facture_inscription_creee"])

    def test_get_inscription_billing_history_handles_missing_metadata(self):
        from joatham_apprenants.models import Apprenant, Formation, InscriptionFormation

        apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Audit 2", prenom="Eleve")
        formation = Formation.objects.create(entreprise=self.entreprise, nom="Word", prix=Decimal("150.00"))
        inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise,
            apprenant=apprenant,
            formation=formation,
            montant_prevu=Decimal("150.00"),
        )

        ActivityLog.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.gestionnaire,
            action="facture_existante_liee_inscription",
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=inscription.id,
            description="Facture liee sans metadata complete.",
            metadata={},
        )
        ActivityLog.objects.create(
            entreprise=self.entreprise_b,
            utilisateur=None,
            action="facture_deliee_inscription",
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=inscription.id,
            description="Autre entreprise.",
            metadata={},
        )

        history = get_inscription_billing_history(inscription)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["facture_numero"], "")


class SuperAdminDashboardTests(TestCase):
    def setUp(self):
        self.plan_basic = Abonnement.objects.create(nom="Basic", code="basic", prix=10, duree_jours=30, actif=True)
        self.plan_pro = Abonnement.objects.create(nom="Pro", code="pro", prix=30, duree_jours=30, actif=True)
        self.entreprise_a = create_entreprise("Entreprise Alpha")
        self.entreprise_b = create_entreprise("Entreprise Beta")
        self.owner = create_user("owner-super-test", "proprietaire", self.entreprise_a)
        self.super_admin = User.objects.create_user(
            username="superadmin",
            password="testpass123",
            role="super_admin",
            entreprise=None,
            email="superadmin@example.com",
        )
        AbonnementEntreprise.objects.create(
            entreprise=self.entreprise_a,
            plan=self.plan_basic,
            statut=AbonnementEntreprise.Statut.ESSAI,
            date_debut=date.today(),
            date_fin=date.today(),
            essai=True,
            actif=True,
        )
        AbonnementEntreprise.objects.create(
            entreprise=self.entreprise_b,
            plan=self.plan_pro,
            statut=AbonnementEntreprise.Statut.ACTIF,
            date_debut=date.today(),
            date_fin=date.today(),
            essai=False,
            actif=True,
        )
        create_user("manager-alpha", "gestionnaire", self.entreprise_a)
        create_user("accountant-alpha", "comptable", self.entreprise_a)

    def test_super_admin_dashboard_is_restricted_to_super_admin(self):
        self.client.force_login(self.owner)
        forbidden = self.client.get(reverse("super_admin_dashboard"))
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.super_admin)
        allowed = self.client.get(reverse("super_admin_dashboard"))
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "Super admin")
        self.assertContains(allowed, "Entreprise Alpha")
        self.assertContains(allowed, "Entreprise Beta")
        self.super_admin.refresh_from_db()
        self.assertIsNone(self.super_admin.entreprise_id)

    def test_super_admin_dashboard_shows_global_company_snapshot(self):
        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("super_admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["counts"]["total_entreprises"], 2)
        self.assertEqual(response.context["counts"]["essai"], 1)
        self.assertEqual(response.context["counts"]["actif"], 1)
        self.assertContains(response, "Basic")
        self.assertContains(response, "Pro")
        self.assertContains(response, "3")
        self.assertContains(response, "Rechercher une entreprise")
        self.assertContains(response, "Filtrer par statut")

    def test_super_admin_dashboard_filters_companies_by_name_and_status(self):
        self.client.force_login(self.super_admin)

        search_response = self.client.get(reverse("super_admin_dashboard"), {"q": "Alpha"})
        self.assertEqual(search_response.status_code, 200)
        self.assertContains(search_response, "Entreprise Alpha")
        self.assertNotContains(search_response, "Entreprise Beta")

        status_response = self.client.get(reverse("super_admin_dashboard"), {"statut": "actif"})
        self.assertEqual(status_response.status_code, 200)
        self.assertContains(status_response, "Entreprise Beta")
        self.assertNotContains(status_response, "Entreprise Alpha")

    def test_super_admin_can_activate_suspend_extend_trial_and_change_plan(self):
        self.client.force_login(self.super_admin)

        activate_response = self.client.post(
            reverse("super_admin_dashboard"),
            {
                "action": "activate",
                "entreprise_id": self.entreprise_a.id,
                "plan_id": self.plan_pro.id,
            },
        )
        self.assertRedirects(activate_response, reverse("super_admin_dashboard"))
        subscription_a = AbonnementEntreprise.objects.get(entreprise=self.entreprise_a)
        self.assertEqual(subscription_a.statut, AbonnementEntreprise.Statut.ACTIF)
        self.assertEqual(subscription_a.plan, self.plan_pro)

        suspend_response = self.client.post(
            reverse("super_admin_dashboard"),
            {
                "action": "suspend",
                "entreprise_id": self.entreprise_b.id,
            },
        )
        self.assertRedirects(suspend_response, reverse("super_admin_dashboard"))
        subscription_b = AbonnementEntreprise.objects.get(entreprise=self.entreprise_b)
        self.assertEqual(subscription_b.statut, AbonnementEntreprise.Statut.SUSPENDU)

        change_plan_response = self.client.post(
            reverse("super_admin_dashboard"),
            {
                "action": "change_plan",
                "entreprise_id": self.entreprise_b.id,
                "plan_id": self.plan_basic.id,
            },
        )
        self.assertRedirects(change_plan_response, reverse("super_admin_dashboard"))
        subscription_b.refresh_from_db()
        self.assertEqual(subscription_b.plan, self.plan_basic)

        previous_end = subscription_b.date_fin
        extend_response = self.client.post(
            reverse("super_admin_dashboard"),
            {
                "action": "extend_trial",
                "entreprise_id": self.entreprise_b.id,
                "trial_days": 7,
                "plan_id": self.plan_basic.id,
            },
        )
        self.assertRedirects(extend_response, reverse("super_admin_dashboard"))
        subscription_b.refresh_from_db()
        self.assertEqual(subscription_b.statut, AbonnementEntreprise.Statut.ESSAI)
        self.assertEqual(subscription_b.plan, self.plan_basic)
        self.assertGreater(subscription_b.date_fin, previous_end)


class SubscriptionPaymentTests(TestCase):
    def setUp(self):
        self.plan_basic = Abonnement.objects.create(nom="Basic", code="basic", prix=10, duree_jours=30, actif=True)
        self.plan_pro = Abonnement.objects.create(nom="Pro", code="pro", prix=30, duree_jours=30, actif=True)
        self.entreprise = create_entreprise("Entreprise Paiement")
        self.owner = create_user("owner-payment", "proprietaire", self.entreprise)
        self.super_admin = User.objects.create_user(
            username="superadmin-payment",
            password="testpass123",
            role="super_admin",
            entreprise=None,
            email="superadmin-payment@example.com",
        )

    def test_owner_can_create_subscription_payment_request_without_activation(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("subscription_payment_create"),
            {
                "plan": self.plan_basic.id,
                "duree": PaiementAbonnement.Duree.TRIMESTRIEL,
                "reference_paiement": "MOMO-123",
            },
        )

        self.assertRedirects(response, reverse("subscription_overview"))
        paiement = PaiementAbonnement.objects.get(entreprise=self.entreprise)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_ATTENTE)
        self.assertEqual(paiement.montant, Decimal("30"))
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    def test_super_admin_validation_activates_subscription(self):
        paiement = create_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_pro,
            duree=PaiementAbonnement.Duree.MENSUEL,
            reference_paiement="BANK-001",
            utilisateur=self.owner,
        )

        subscription = validate_subscription_payment(paiement=paiement, super_admin=self.super_admin)
        paiement.refresh_from_db()
        self.entreprise.refresh_from_db()

        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.VALIDE)
        self.assertEqual(paiement.valide_par, self.super_admin)
        self.assertEqual(subscription.statut, AbonnementEntreprise.Statut.ACTIF)
        self.assertEqual(subscription.plan, self.plan_pro)
        self.assertEqual(self.entreprise.abonnement, self.plan_pro)
        self.assertEqual(self.entreprise.date_expiration, subscription.date_fin)

    def test_super_admin_refusal_does_not_activate_subscription(self):
        paiement = create_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            reference_paiement="REFUSE-001",
            utilisateur=self.owner,
        )

        refuse_subscription_payment(paiement=paiement, super_admin=self.super_admin)
        paiement.refresh_from_db()

        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.REFUSE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    def test_super_admin_dashboard_can_validate_and_refuse_pending_payments(self):
        paiement_validate = create_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            reference_paiement="MOMO-VALID",
            utilisateur=self.owner,
        )
        other_entreprise = create_entreprise("Entreprise Paiement Refus")
        paiement_refuse = create_subscription_payment_request(
            entreprise=other_entreprise,
            plan=self.plan_pro,
            duree=PaiementAbonnement.Duree.ANNUEL,
            reference_paiement="MOMO-REFUSE",
            utilisateur=None,
        )

        self.client.force_login(self.super_admin)
        dashboard = self.client.get(reverse("super_admin_dashboard"))
        self.assertContains(dashboard, "Paiements d'abonnement en attente")
        self.assertContains(dashboard, "MOMO-VALID")

        validate_response = self.client.post(
            reverse("super_admin_dashboard"),
            {"action": "validate_payment", "paiement_id": paiement_validate.id},
        )
        self.assertRedirects(validate_response, reverse("super_admin_dashboard"))
        paiement_validate.refresh_from_db()
        self.assertEqual(paiement_validate.statut, PaiementAbonnement.Statut.VALIDE)

        refuse_response = self.client.post(
            reverse("super_admin_dashboard"),
            {"action": "refuse_payment", "paiement_id": paiement_refuse.id},
        )
        self.assertRedirects(refuse_response, reverse("super_admin_dashboard"))
        paiement_refuse.refresh_from_db()
        self.assertEqual(paiement_refuse.statut, PaiementAbonnement.Statut.REFUSE)
