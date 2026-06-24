from io import BytesIO
from zipfile import ZipFile
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import Http404
from django.test import TestCase
from django.urls import reverse

from core.models import ActivityLog
from core.selectors.audit import get_inscription_billing_history
from core.services.subscription import activate_subscription_for_entreprise
from joatham_billing.models import Facture
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement

from .models import Apprenant, Formation, InscriptionFormation, PaiementInscription
from .selectors.apprenants import (
    get_apprenants_by_entreprise,
    get_formations_by_entreprise,
    get_inscription_by_entreprise,
    get_inscriptions_by_entreprise,
    get_paiement_documents_by_id,
    get_paiements_by_inscription,
)
from .selectors.dashboard import get_apprenants_dashboard_data
from .services.apprenants_service import (
    create_apprenant,
    create_formation,
    create_paiement_inscription,
    inscrire_apprenant_a_formation,
    toggle_formation_active,
    update_inscription_montant_prevu,
    update_formation,
)
from .services.billing_integration import generate_facture_for_inscription, link_facture_to_inscription, unlink_facture_from_inscription


class ApprenantsSelectorsTests(TestCase):
    def setUp(self):
        self.entreprise_a = create_entreprise("Entreprise Apprenants A")
        self.entreprise_b = create_entreprise("Entreprise Apprenants B")
        self.apprenant_a = Apprenant.objects.create(entreprise=self.entreprise_a, nom="Alpha", prenom="A")
        self.apprenant_b = Apprenant.objects.create(entreprise=self.entreprise_b, nom="Beta", prenom="B")
        self.formation_a = Formation.objects.create(entreprise=self.entreprise_a, nom="Comptabilite", prix=Decimal("120.00"))
        self.formation_b = Formation.objects.create(entreprise=self.entreprise_b, nom="Paie", prix=Decimal("80.00"))
        self.inscription_a = InscriptionFormation.objects.create(
            entreprise=self.entreprise_a,
            apprenant=self.apprenant_a,
            formation=self.formation_a,
            montant_prevu=Decimal("120.00"),
            montant_paye=Decimal("20.00"),
        )
        self.paiement_a = PaiementInscription.objects.create(
            entreprise=self.entreprise_a,
            inscription=self.inscription_a,
            montant=Decimal("20.00"),
        )

    def test_apprenant_selector_is_scoped_to_entreprise(self):
        self.assertEqual(list(get_apprenants_by_entreprise(self.entreprise_a)), [self.apprenant_a])

    def test_formation_selector_is_scoped_to_entreprise(self):
        self.assertEqual(list(get_formations_by_entreprise(self.entreprise_a)), [self.formation_a])

    def test_inscription_selector_is_scoped_to_entreprise(self):
        self.assertEqual(list(get_inscriptions_by_entreprise(self.entreprise_a)), [self.inscription_a])

    def test_get_inscription_by_entreprise_rejects_other_tenant(self):
        with self.assertRaises(Http404):
            get_inscription_by_entreprise(self.entreprise_b, self.inscription_a.id)

    def test_paiement_selector_is_scoped_to_entreprise(self):
        self.assertEqual(list(get_paiements_by_inscription(self.entreprise_a, self.inscription_a)), [self.paiement_a])

    def test_payment_documents_follow_cumulative_balance(self):
        apprenant = Apprenant.objects.create(entreprise=self.entreprise_a, nom="Tranche", prenom="Test")
        formation = Formation.objects.create(entreprise=self.entreprise_a, nom="Formation Tranches", prix=Decimal("150.00"))
        inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise_a,
            apprenant=apprenant,
            formation=formation,
            montant_prevu=Decimal("150.00"),
        )
        premier_paiement = PaiementInscription.objects.create(
            entreprise=self.entreprise_a,
            inscription=inscription,
            montant=Decimal("50.00"),
        )
        dernier_paiement = PaiementInscription.objects.create(
            entreprise=self.entreprise_a,
            inscription=inscription,
            montant=Decimal("100.00"),
        )

        documents = get_paiement_documents_by_id(inscription)

        self.assertEqual(documents[premier_paiement.id]["document_type"], "recu")
        self.assertEqual(documents[premier_paiement.id]["montant_paye_cumule"], Decimal("50.00"))
        self.assertEqual(documents[premier_paiement.id]["solde_restant"], Decimal("100.00"))
        self.assertEqual(documents[dernier_paiement.id]["document_type"], "quittance")
        self.assertEqual(documents[dernier_paiement.id]["montant_paye_cumule"], Decimal("150.00"))
        self.assertEqual(documents[dernier_paiement.id]["solde_restant"], Decimal("0.00"))

    def test_overpaid_payment_document_tracks_overpayment(self):
        apprenant = Apprenant.objects.create(entreprise=self.entreprise_a, nom="Over", prenom="Paid")
        formation = Formation.objects.create(entreprise=self.entreprise_a, nom="Formation Over", prix=Decimal("150.00"))
        inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise_a,
            apprenant=apprenant,
            formation=formation,
            montant_prevu=Decimal("150.00"),
        )
        paiement = PaiementInscription.objects.create(
            entreprise=self.entreprise_a,
            inscription=inscription,
            montant=Decimal("175.00"),
        )

        document = get_paiement_documents_by_id(inscription)[paiement.id]

        self.assertEqual(document["document_type"], "quittance")
        self.assertEqual(document["solde_restant"], Decimal("0.00"))
        self.assertEqual(document["trop_percu"], Decimal("25.00"))


class ApprenantsServicesTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Services")
        self.autre_entreprise = create_entreprise("Entreprise Externe")
        self.user = create_user("owner-apprenant", "proprietaire", self.entreprise)
        self.apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Kiala", prenom="Marie")
        self.formation = Formation.objects.create(
            entreprise=self.entreprise,
            nom="Gestion",
            prix=Decimal("250.00"),
            duree="3 mois",
        )
        self.formation_externe = Formation.objects.create(
            entreprise=self.autre_entreprise,
            nom="Formation Externe",
            prix=Decimal("99.00"),
        )
        self.inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise,
            apprenant=self.apprenant,
            formation=self.formation,
            montant_prevu=Decimal("250.00"),
            montant_paye=Decimal("0.00"),
        )

    def test_create_apprenant_creates_audit_event(self):
        apprenant = create_apprenant(
            entreprise=self.entreprise,
            nom="Ngoma",
            prenom="Paul",
            telephone="+243000000000",
            email="paul@example.com",
            utilisateur=self.user,
        )

        self.assertEqual(apprenant.entreprise, self.entreprise)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.user,
                action="creation_apprenant",
                objet_id=apprenant.id,
            ).exists()
        )

    def test_create_formation_creates_audit_event(self):
        formation = create_formation(
            entreprise=self.entreprise,
            nom="Word avance",
            prix=Decimal("90.00"),
            utilisateur=self.user,
        )

        self.assertEqual(formation.entreprise, self.entreprise)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.user,
                action="formation_creee",
                objet_id=formation.id,
            ).exists()
        )

    def test_update_formation_creates_audit_event(self):
        update_formation(
            self.formation,
            nom="Gestion avancee",
            description="Nouvelle version",
            prix=Decimal("275.00"),
            duree="4 mois",
            actif=True,
            utilisateur=self.user,
        )

        self.formation.refresh_from_db()
        self.assertEqual(self.formation.nom, "Gestion avancee")
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.user,
                action="formation_modifiee",
                objet_id=self.formation.id,
            ).exists()
        )

    def test_toggle_formation_active_creates_audit_event(self):
        toggle_formation_active(self.formation, actif=False, utilisateur=self.user)

        self.formation.refresh_from_db()
        self.assertFalse(self.formation.actif)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.user,
                action="formation_statut_modifie",
                objet_id=self.formation.id,
            ).exists()
        )

    def test_inscrire_apprenant_uses_formation_price_when_amount_missing(self):
        autre_apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Malu", prenom="P")
        inscription = inscrire_apprenant_a_formation(
            entreprise=self.entreprise,
            apprenant_id=autre_apprenant.id,
            formation_id=self.formation.id,
            utilisateur=self.user,
        )

        self.assertEqual(inscription.montant_prevu, Decimal("250.00"))
        self.assertEqual(inscription.solde, Decimal("250.00"))
        self.assertEqual(inscription.statut_paiement, InscriptionFormation.StatutPaiement.IMPAYE)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.user,
                action="inscription_formation_creee",
                objet_id=inscription.id,
            ).exists()
        )

    def test_inscrire_apprenant_refuses_negative_total_amount(self):
        with self.assertRaises(ValidationError):
            inscrire_apprenant_a_formation(
                entreprise=self.entreprise,
                apprenant_id=self.apprenant.id,
                formation_id=self.formation.id,
                montant_prevu=Decimal("-1.00"),
                utilisateur=self.user,
            )

    def test_inscrire_apprenant_refuses_negative_initial_payment(self):
        with self.assertRaises(ValidationError):
            inscrire_apprenant_a_formation(
                entreprise=self.entreprise,
                apprenant_id=self.apprenant.id,
                formation_id=self.formation.id,
                montant_prevu=Decimal("250.00"),
                montant_paye=Decimal("-1.00"),
                utilisateur=self.user,
            )

    def test_inscrire_apprenant_allows_initial_overpayment_as_historical_payment(self):
        apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Trop", prenom="Percu")
        inscription = inscrire_apprenant_a_formation(
            entreprise=self.entreprise,
            apprenant_id=apprenant.id,
            formation_id=self.formation.id,
            montant_prevu=Decimal("250.00"),
            montant_paye=Decimal("251.00"),
            utilisateur=self.user,
        )

        self.assertEqual(inscription.montant_paye, Decimal("251.00"))
        self.assertEqual(inscription.solde, Decimal("0.00"))
        self.assertEqual(inscription.trop_percu, Decimal("1.00"))
        self.assertEqual(inscription.statut_paiement, InscriptionFormation.StatutPaiement.PAYE)
        self.assertTrue(PaiementInscription.objects.filter(inscription=inscription, montant=Decimal("251.00")).exists())

    def test_inscrire_apprenant_refuses_unknown_status(self):
        apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Statut", prenom="Inconnu")

        with self.assertRaises(ValidationError):
            inscrire_apprenant_a_formation(
                entreprise=self.entreprise,
                apprenant_id=apprenant.id,
                formation_id=self.formation.id,
                statut="archive",
                montant_prevu=Decimal("250.00"),
                utilisateur=self.user,
            )

    def test_inscrire_apprenant_with_zero_initial_payment_is_unpaid(self):
        apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Zero", prenom="Initial")
        inscription = inscrire_apprenant_a_formation(
            entreprise=self.entreprise,
            apprenant_id=apprenant.id,
            formation_id=self.formation.id,
            montant_prevu=Decimal("250.00"),
            montant_paye=Decimal("0.00"),
            utilisateur=self.user,
        )

        self.assertEqual(inscription.montant_paye, Decimal("0.00"))
        self.assertEqual(inscription.solde, Decimal("250.00"))
        self.assertEqual(inscription.statut_paiement, InscriptionFormation.StatutPaiement.IMPAYE)
        self.assertFalse(PaiementInscription.objects.filter(inscription=inscription).exists())

    def test_inscrire_apprenant_with_partial_initial_payment_is_partial(self):
        apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Partiel", prenom="Initial")
        inscription = inscrire_apprenant_a_formation(
            entreprise=self.entreprise,
            apprenant_id=apprenant.id,
            formation_id=self.formation.id,
            montant_prevu=Decimal("250.00"),
            montant_paye=Decimal("100.00"),
            utilisateur=self.user,
        )

        self.assertEqual(inscription.montant_paye, Decimal("100.00"))
        self.assertEqual(inscription.solde, Decimal("150.00"))
        self.assertEqual(inscription.statut_paiement, InscriptionFormation.StatutPaiement.PARTIEL)
        self.assertTrue(PaiementInscription.objects.filter(inscription=inscription, montant=Decimal("100.00")).exists())

    def test_inscrire_apprenant_with_full_initial_payment_is_paid(self):
        apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Paye", prenom="Initial")
        inscription = inscrire_apprenant_a_formation(
            entreprise=self.entreprise,
            apprenant_id=apprenant.id,
            formation_id=self.formation.id,
            montant_prevu=Decimal("250.00"),
            montant_paye=Decimal("250.00"),
            utilisateur=self.user,
        )

        self.assertEqual(inscription.montant_paye, Decimal("250.00"))
        self.assertEqual(inscription.solde, Decimal("0.00"))
        self.assertEqual(inscription.statut_paiement, InscriptionFormation.StatutPaiement.PAYE)

    def test_inscrire_apprenant_refuses_other_entreprise_formation(self):
        with self.assertRaises(Http404):
            inscrire_apprenant_a_formation(
                entreprise=self.entreprise,
                apprenant_id=self.apprenant.id,
                formation_id=self.formation_externe.id,
                utilisateur=self.user,
            )

    def test_create_paiement_updates_inscription_totals_and_audit(self):
        paiement = create_paiement_inscription(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            montant=Decimal("100.00"),
            mode_paiement=PaiementInscription.ModePaiement.VIREMENT,
            reference="PAY-001",
            utilisateur=self.user,
        )

        self.inscription.refresh_from_db()
        self.assertEqual(paiement.entreprise, self.entreprise)
        self.assertEqual(self.inscription.montant_paye, Decimal("100.00"))
        self.assertEqual(self.inscription.solde, Decimal("150.00"))
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.user,
                action="paiement_inscription_cree",
                objet_id=paiement.id,
            ).exists()
        )

    def test_create_paiement_refuses_zero_amount(self):
        with self.assertRaises(ValidationError):
            create_paiement_inscription(
                entreprise=self.entreprise,
                inscription_id=self.inscription.id,
                montant=Decimal("0.00"),
                utilisateur=self.user,
            )

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_paye, Decimal("0.00"))
        self.assertEqual(self.inscription.solde, Decimal("250.00"))
        self.assertFalse(PaiementInscription.objects.filter(inscription=self.inscription).exists())

    def test_create_paiement_refuses_negative_amount(self):
        with self.assertRaises(ValidationError):
            create_paiement_inscription(
                entreprise=self.entreprise,
                inscription_id=self.inscription.id,
                montant=Decimal("-10.00"),
                utilisateur=self.user,
            )

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_paye, Decimal("0.00"))
        self.assertEqual(self.inscription.solde, Decimal("250.00"))
        self.assertFalse(PaiementInscription.objects.filter(inscription=self.inscription).exists())

    def test_create_paiement_allows_amount_greater_than_remaining_balance(self):
        paiement = create_paiement_inscription(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            montant=Decimal("251.00"),
            utilisateur=self.user,
        )

        self.inscription.refresh_from_db()
        self.assertEqual(paiement.montant, Decimal("251.00"))
        self.assertEqual(self.inscription.montant_paye, Decimal("251.00"))
        self.assertEqual(self.inscription.solde, Decimal("0.00"))
        self.assertEqual(self.inscription.trop_percu, Decimal("1.00"))
        self.assertEqual(self.inscription.statut_paiement, InscriptionFormation.StatutPaiement.PAYE)

    def test_create_paiement_refuses_unknown_payment_mode(self):
        with self.assertRaises(ValidationError):
            create_paiement_inscription(
                entreprise=self.entreprise,
                inscription_id=self.inscription.id,
                montant=Decimal("20.00"),
                mode_paiement="crypto",
                utilisateur=self.user,
            )

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_paye, Decimal("0.00"))
        self.assertEqual(self.inscription.solde, Decimal("250.00"))
        self.assertFalse(PaiementInscription.objects.filter(inscription=self.inscription).exists())
        self.assertFalse(ActivityLog.objects.filter(action="paiement_inscription_cree").exists())

    def test_multiple_paiements_recalculate_cumulative_totals(self):
        create_paiement_inscription(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            montant=Decimal("60.00"),
            utilisateur=self.user,
        )
        create_paiement_inscription(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            montant=Decimal("40.00"),
            utilisateur=self.user,
        )

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_paye, Decimal("100.00"))
        self.assertEqual(self.inscription.solde, Decimal("150.00"))
        self.assertEqual(self.inscription.statut_paiement, InscriptionFormation.StatutPaiement.PARTIEL)

    def test_direct_payment_creation_recalculates_totals(self):
        PaiementInscription.objects.create(
            entreprise=self.entreprise,
            inscription=self.inscription,
            montant=Decimal("90.00"),
            utilisateur=self.user,
        )

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_paye, Decimal("90.00"))
        self.assertEqual(self.inscription.solde, Decimal("160.00"))
        self.assertEqual(self.inscription.statut_paiement, InscriptionFormation.StatutPaiement.PARTIEL)

    def test_complete_paiement_marks_inscription_as_paid(self):
        create_paiement_inscription(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            montant=Decimal("250.00"),
            utilisateur=self.user,
        )

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_paye, Decimal("250.00"))
        self.assertEqual(self.inscription.solde, Decimal("0.00"))
        self.assertEqual(self.inscription.statut_paiement, InscriptionFormation.StatutPaiement.PAYE)

    def test_update_inscription_montant_prevu_recalculates_balance(self):
        create_paiement_inscription(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            montant=Decimal("100.00"),
            utilisateur=self.user,
        )

        update_inscription_montant_prevu(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            montant_prevu=Decimal("150.00"),
            utilisateur=self.user,
        )

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_prevu, Decimal("150.00"))
        self.assertEqual(self.inscription.montant_paye, Decimal("100.00"))
        self.assertEqual(self.inscription.solde, Decimal("50.00"))
        self.assertEqual(self.inscription.statut_paiement, InscriptionFormation.StatutPaiement.PARTIEL)

    def test_update_inscription_montant_prevu_keeps_overpayment_as_zero_balance(self):
        create_paiement_inscription(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            montant=Decimal("200.00"),
            utilisateur=self.user,
        )

        update_inscription_montant_prevu(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            montant_prevu=Decimal("150.00"),
            utilisateur=self.user,
        )

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_prevu, Decimal("150.00"))
        self.assertEqual(self.inscription.montant_paye, Decimal("200.00"))
        self.assertEqual(self.inscription.solde, Decimal("0.00"))
        self.assertEqual(self.inscription.trop_percu, Decimal("50.00"))
        self.assertEqual(self.inscription.statut_paiement, InscriptionFormation.StatutPaiement.PAYE)

    def test_create_paiement_refuses_other_entreprise_inscription(self):
        inscription_externe = InscriptionFormation.objects.create(
            entreprise=self.autre_entreprise,
            apprenant=Apprenant.objects.create(entreprise=self.autre_entreprise, nom="Ext", prenom="A"),
            formation=self.formation_externe,
            montant_prevu=Decimal("99.00"),
        )
        with self.assertRaises(Http404):
            create_paiement_inscription(
                entreprise=self.entreprise,
                inscription_id=inscription_externe.id,
                montant=Decimal("20.00"),
                utilisateur=self.user,
            )

    def test_generate_facture_for_inscription_links_facture_and_creates_audit(self):
        facture = generate_facture_for_inscription(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            utilisateur=self.user,
        )

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.facture_id, facture.id)
        self.assertEqual(facture.client_nom, str(self.apprenant))
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.user,
                action="facture_inscription_creee",
                objet_id=self.inscription.id,
            ).exists()
        )

    def test_generate_facture_for_inscription_avoids_duplicate_generation(self):
        generate_facture_for_inscription(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            utilisateur=self.user,
        )

        with self.assertRaises(ValidationError):
            generate_facture_for_inscription(
                entreprise=self.entreprise,
                inscription_id=self.inscription.id,
                utilisateur=self.user,
            )

    def test_generate_facture_for_inscription_is_scoped_to_entreprise(self):
        inscription_externe = InscriptionFormation.objects.create(
            entreprise=self.autre_entreprise,
            apprenant=Apprenant.objects.create(entreprise=self.autre_entreprise, nom="Ext", prenom="A"),
            formation=self.formation_externe,
            montant_prevu=Decimal("99.00"),
        )
        with self.assertRaises(Http404):
            generate_facture_for_inscription(
                entreprise=self.entreprise,
                inscription_id=inscription_externe.id,
                utilisateur=self.user,
            )

    def test_link_existing_facture_to_inscription_succeeds_and_creates_audit(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("250.00"),
        )

        linked = link_facture_to_inscription(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            facture_id=facture.id,
            utilisateur=self.user,
        )

        self.inscription.refresh_from_db()
        self.assertEqual(linked.id, facture.id)
        self.assertEqual(self.inscription.facture_id, facture.id)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.user,
                action="facture_existante_liee_inscription",
                objet_id=self.inscription.id,
            ).exists()
        )

    def test_link_existing_facture_refuses_other_entreprise_facture(self):
        facture_externe = Facture.objects.create(
            entreprise=self.autre_entreprise,
            client_nom="Externe",
            montant=Decimal("99.00"),
        )
        with self.assertRaises(Http404):
            link_facture_to_inscription(
                entreprise=self.entreprise,
                inscription_id=self.inscription.id,
                facture_id=facture_externe.id,
                utilisateur=self.user,
            )


class ApprenantsRoleUiTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise UI Apprenants")
        self.autre_entreprise = create_entreprise("Entreprise UI Apprenants B")
        self.owner = create_user("owner-ui-appr", "proprietaire", self.entreprise)
        self.user = self.owner
        self.comptable = create_user("compta-ui-appr", "comptable", self.entreprise)
        self.plan = Abonnement.objects.create(
            nom="Apprenants UI",
            code="appr-ui",
            prix=10,
            duree_jours=30,
            actif=True,
            modules_inclus=["apprenants"],
        )
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.owner)
        self.apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Alpha", prenom="Test")
        self.formation = Formation.objects.create(entreprise=self.entreprise, nom="Formation", prix=Decimal("100.00"))
        self.inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise,
            apprenant=self.apprenant,
            formation=self.formation,
            montant_prevu=Decimal("100.00"),
            montant_paye=Decimal("0.00"),
        )

    def test_comptable_sees_read_only_apprenants_actions_but_can_add_payment(self):
        self.client.force_login(self.comptable)

        list_response = self.client.get(reverse("apprenant_list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, reverse("apprenant_create"))
        self.assertNotContains(list_response, reverse("inscription_create"))
        self.assertContains(list_response, reverse("paiement_inscription_create", args=[self.inscription.id]))

        formation_response = self.client.get(reverse("formation_list"))
        self.assertEqual(formation_response.status_code, 200)
        self.assertNotContains(formation_response, reverse("formation_create"))
        self.assertContains(formation_response, "Lecture seule")

    def test_comptable_can_access_inscription_payment_form_but_not_billing_link_actions(self):
        self.client.force_login(self.comptable)

        detail_response = self.client.get(reverse("inscription_detail", args=[self.inscription.id]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, reverse("paiement_inscription_create", args=[self.inscription.id]))
        self.assertNotContains(detail_response, "Generer une facture")
        self.assertNotContains(detail_response, "Lier une facture existante")

    def test_link_existing_facture_refuses_already_linked_inscription(self):
        facture_1 = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("100.00"),
        )
        facture_2 = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("150.00"),
        )
        self.inscription.facture = facture_1
        self.inscription.save(update_fields=["facture"])

        with self.assertRaises(ValidationError):
            link_facture_to_inscription(
                entreprise=self.entreprise,
                inscription_id=self.inscription.id,
                facture_id=facture_2.id,
                utilisateur=self.user,
            )

    def test_link_existing_facture_refuses_facture_already_linked_elsewhere(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom="Client Test",
            montant=Decimal("100.00"),
        )
        other_inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise,
            apprenant=Apprenant.objects.create(entreprise=self.entreprise, nom="Autre", prenom="A"),
            formation=self.formation,
            montant_prevu=Decimal("100.00"),
            facture=facture,
        )
        self.assertIsNotNone(other_inscription.facture_id)

        with self.assertRaises(ValidationError):
            link_facture_to_inscription(
                entreprise=self.entreprise,
                inscription_id=self.inscription.id,
                facture_id=facture.id,
                utilisateur=self.user,
            )

    def test_unlink_facture_from_inscription_succeeds_when_safe(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("250.00"),
        )
        self.inscription.facture = facture
        self.inscription.save(update_fields=["facture"])

        unlinked = unlink_facture_from_inscription(
            entreprise=self.entreprise,
            inscription_id=self.inscription.id,
            facture_id=facture.id,
            utilisateur=self.user,
        )

        self.inscription.refresh_from_db()
        self.assertEqual(unlinked.id, facture.id)
        self.assertIsNone(self.inscription.facture_id)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.user,
                action="facture_deliee_inscription",
                objet_id=self.inscription.id,
            ).exists()
        )

    def test_unlink_facture_refuses_when_payments_exist(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("250.00"),
            statut=Facture.Statut.EMISE,
        )
        self.inscription.facture = facture
        self.inscription.save(update_fields=["facture"])
        facture.paiements.create(
            entreprise=self.entreprise,
            montant=Decimal("50.00"),
            mode="especes",
        )

        with self.assertRaises(ValidationError):
            unlink_facture_from_inscription(
                entreprise=self.entreprise,
                inscription_id=self.inscription.id,
                facture_id=facture.id,
                utilisateur=self.user,
            )

    def test_unlink_facture_refuses_when_facture_is_payee(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("250.00"),
            statut=Facture.Statut.PAYEE,
            paye=True,
        )
        self.inscription.facture = facture
        self.inscription.save(update_fields=["facture"])

        with self.assertRaises(ValidationError):
            unlink_facture_from_inscription(
                entreprise=self.entreprise,
                inscription_id=self.inscription.id,
                facture_id=facture.id,
                utilisateur=self.user,
            )

    def test_unlink_facture_refuses_other_entreprise_facture(self):
        facture_externe = Facture.objects.create(
            entreprise=self.autre_entreprise,
            client_nom="Externe",
            montant=Decimal("100.00"),
        )
        self.inscription.facture = facture_externe
        self.inscription.save(update_fields=["facture"])

        with self.assertRaises(Http404):
            unlink_facture_from_inscription(
                entreprise=self.entreprise,
                inscription_id=self.inscription.id,
                facture_id=facture_externe.id,
                utilisateur=self.user,
            )

    def test_unlink_facture_refuses_when_no_facture_is_linked(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("100.00"),
        )
        with self.assertRaises(ValidationError):
            unlink_facture_from_inscription(
                entreprise=self.entreprise,
                inscription_id=self.inscription.id,
                facture_id=facture.id,
                utilisateur=self.user,
            )


class ApprenantsDashboardSelectorsTests(TestCase):
    def setUp(self):
        self.entreprise_a = create_entreprise("Entreprise Dashboard A")
        self.entreprise_b = create_entreprise("Entreprise Dashboard B")

        self.apprenant_a1 = Apprenant.objects.create(entreprise=self.entreprise_a, nom="A1", actif=True)
        self.apprenant_a2 = Apprenant.objects.create(entreprise=self.entreprise_a, nom="A2", actif=True)
        Apprenant.objects.create(entreprise=self.entreprise_a, nom="A3", actif=False)
        Apprenant.objects.create(entreprise=self.entreprise_b, nom="B1", actif=True)

        self.formation_a1 = Formation.objects.create(entreprise=self.entreprise_a, nom="Excel", prix=Decimal("100.00"), actif=True)
        self.formation_a2 = Formation.objects.create(entreprise=self.entreprise_a, nom="Word", prix=Decimal("200.00"), actif=True)
        Formation.objects.create(entreprise=self.entreprise_a, nom="Archive", prix=Decimal("50.00"), actif=False)
        Formation.objects.create(entreprise=self.entreprise_b, nom="B Formation", prix=Decimal("999.00"), actif=True)

        self.inscription_a1 = InscriptionFormation.objects.create(
            entreprise=self.entreprise_a,
            apprenant=self.apprenant_a1,
            formation=self.formation_a1,
            date_inscription=date(2026, 1, 15),
            statut=InscriptionFormation.Statut.EN_COURS,
            montant_prevu=Decimal("100.00"),
            montant_paye=Decimal("40.00"),
            solde=Decimal("60.00"),
        )
        self.inscription_a0 = InscriptionFormation.objects.create(
            entreprise=self.entreprise_a,
            apprenant=self.apprenant_a1,
            formation=self.formation_a2,
            date_inscription=date(2026, 1, 10),
            statut=InscriptionFormation.Statut.EN_COURS,
            montant_prevu=Decimal("150.00"),
            montant_paye=Decimal("50.00"),
            solde=Decimal("100.00"),
        )
        self.inscription_a2 = InscriptionFormation.objects.create(
            entreprise=self.entreprise_a,
            apprenant=self.apprenant_a2,
            formation=self.formation_a2,
            date_inscription=date(2026, 2, 1),
            statut=InscriptionFormation.Statut.TERMINEE,
            montant_prevu=Decimal("200.00"),
            montant_paye=Decimal("200.00"),
            solde=Decimal("0.00"),
        )
        InscriptionFormation.objects.create(
            entreprise=self.entreprise_b,
            apprenant=Apprenant.objects.create(entreprise=self.entreprise_b, nom="B2"),
            formation=Formation.objects.get(entreprise=self.entreprise_b, nom="B Formation"),
            statut=InscriptionFormation.Statut.EN_COURS,
            montant_prevu=Decimal("999.00"),
            montant_paye=Decimal("100.00"),
            solde=Decimal("899.00"),
        )

    def test_dashboard_selector_returns_expected_kpis(self):
        data = get_apprenants_dashboard_data(self.entreprise_a)

        self.assertEqual(data["kpis"]["active_apprenants"], 2)
        self.assertEqual(data["kpis"]["active_formations"], 2)
        self.assertEqual(data["kpis"]["total_inscriptions"], 3)
        self.assertEqual(data["kpis"]["total_du"], Decimal("450.00"))
        self.assertEqual(data["kpis"]["total_paye"], Decimal("290.00"))
        self.assertEqual(data["kpis"]["total_restant"], Decimal("160.00"))
        self.assertEqual(data["kpis"]["overdue_inscriptions"], 2)
        self.assertEqual(data["kpis"]["status_breakdown"][InscriptionFormation.Statut.EN_COURS], 2)
        self.assertEqual(data["kpis"]["status_breakdown"][InscriptionFormation.Statut.TERMINEE], 1)

    def test_dashboard_selector_filters_by_formation(self):
        data = get_apprenants_dashboard_data(self.entreprise_a, formation_id=self.formation_a1.id)

        self.assertEqual(data["kpis"]["total_inscriptions"], 1)
        self.assertEqual(data["kpis"]["total_du"], Decimal("100.00"))
        self.assertEqual(list(data["inscriptions"]), [self.inscription_a1])

    def test_dashboard_selector_filters_by_statut(self):
        data = get_apprenants_dashboard_data(self.entreprise_a, statut=InscriptionFormation.Statut.TERMINEE)

        self.assertEqual(data["kpis"]["total_inscriptions"], 1)
        self.assertEqual(data["kpis"]["total_restant"], Decimal("0.00"))
        self.assertEqual(list(data["inscriptions"]), [self.inscription_a2])

    def test_dashboard_alerts_return_oldest_unpaid_inscriptions_in_oldest_first_order(self):
        data = get_apprenants_dashboard_data(self.entreprise_a)
        oldest_unpaid = list(data["alerts"]["oldest_unpaid_inscriptions"])

        self.assertEqual(oldest_unpaid[0], self.inscription_a0)
        self.assertEqual(oldest_unpaid[1], self.inscription_a1)

    def test_dashboard_alerts_aggregate_largest_balance_learners(self):
        data = get_apprenants_dashboard_data(self.entreprise_a)
        learners = list(data["alerts"]["largest_balance_learners"])

        self.assertEqual(learners[0]["apprenant_id"], self.apprenant_a1.id)
        self.assertEqual(learners[0]["total_solde"], Decimal("160.00"))
        self.assertEqual(learners[0]["inscriptions_count"], 2)

    def test_dashboard_alerts_aggregate_largest_balance_formations(self):
        data = get_apprenants_dashboard_data(self.entreprise_a)
        formations = list(data["alerts"]["largest_balance_formations"])

        self.assertEqual(formations[0]["formation_id"], self.formation_a2.id)
        self.assertEqual(formations[0]["total_solde"], Decimal("100.00"))

    def test_dashboard_alerts_include_only_active_unpaid_inscriptions(self):
        data = get_apprenants_dashboard_data(self.entreprise_a)
        active_unpaid = list(data["alerts"]["active_unpaid_inscriptions"])

        self.assertEqual(active_unpaid, [self.inscription_a0, self.inscription_a1])


class ApprenantsViewsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Vue")
        self.autre_entreprise = create_entreprise("Entreprise Vue B")
        self.proprietaire = create_user("owner-views", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("gestion-views", "gestionnaire", self.entreprise)
        self.comptable = create_user("compta-views", "comptable", self.entreprise)
        self.plan = Abonnement.objects.create(
            nom="Apprenants",
            code="apprenants",
            prix=24,
            duree_jours=30,
            actif=True,
            modules_inclus=["apprenants"],
        )
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.proprietaire)
        activate_subscription_for_entreprise(entreprise=self.autre_entreprise, plan=self.plan)
        self.apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Lema", prenom="Sarah")
        self.apprenant_externe = Apprenant.objects.create(entreprise=self.autre_entreprise, nom="Externe", prenom="Test")
        self.formation = Formation.objects.create(entreprise=self.entreprise, nom="Excel", prix=Decimal("75.00"))
        self.formation_externe = Formation.objects.create(entreprise=self.autre_entreprise, nom="Externe", prix=Decimal("150.00"))
        self.inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise,
            apprenant=self.apprenant,
            formation=self.formation,
            montant_prevu=Decimal("75.00"),
            montant_paye=Decimal("25.00"),
        )
        PaiementInscription.objects.create(
            entreprise=self.entreprise,
            inscription=self.inscription,
            montant=Decimal("25.00"),
            utilisateur=self.gestionnaire,
        )
        self.seconde_formation = Formation.objects.create(entreprise=self.entreprise, nom="PowerPoint", prix=Decimal("120.00"))
        self.seconde_inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise,
            apprenant=Apprenant.objects.create(entreprise=self.entreprise, nom="Mbala", prenom="Chris", actif=True),
            formation=self.seconde_formation,
            statut=InscriptionFormation.Statut.TERMINEE,
            montant_prevu=Decimal("120.00"),
            montant_paye=Decimal("120.00"),
            solde=Decimal("0.00"),
        )
        self.inscription_externe = InscriptionFormation.objects.create(
            entreprise=self.autre_entreprise,
            apprenant=self.apprenant_externe,
            formation=self.formation_externe,
            montant_prevu=Decimal("150.00"),
            montant_paye=Decimal("0.00"),
            solde=Decimal("150.00"),
        )

    def test_comptable_can_view_apprenants_but_not_create(self):
        self.client.force_login(self.comptable)

        list_response = self.client.get(reverse("apprenant_list"))
        create_response = self.client.get(reverse("apprenant_create"))

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "Lema")
        self.assertNotContains(list_response, "Externe")
        self.assertEqual(create_response.status_code, 403)

    def test_comptable_can_access_apprenants_dashboard(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("apprenants_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard apprenants")
        self.assertEqual(response.context["kpis"]["total_inscriptions"], 2)
        self.assertEqual(response.context["kpis"]["total_restant"], Decimal("50.00"))
        self.assertIn("alerts", response.context)
        self.assertNotContains(response, "150.00")

    def test_apprenants_module_access_blocks_direct_urls(self):
        self.plan.modules_inclus = ["dashboard"]
        self.plan.save(update_fields=["modules_inclus"])
        self.client.force_login(self.gestionnaire)

        blocked_urls = [
            reverse("apprenant_list"),
            reverse("formation_list"),
            reverse("formation_update", args=[self.formation.id]),
            reverse("inscription_create"),
            reverse("inscription_detail", args=[self.inscription.id]),
            reverse("paiement_inscription_create", args=[self.inscription.id]),
            reverse("inscription_generate_facture", args=[self.inscription.id]),
            reverse("apprenants_pdf"),
            reverse("inscriptions_excel"),
        ]

        for url in blocked_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("module=apprenants", response["Location"])

    def test_gestionnaire_can_create_apprenant(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("apprenant_create"),
            {
                "nom": "Mavungu",
                "prenom": "Alice",
                "telephone": "+243111111111",
                "email": "alice@example.com",
                "actif": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Apprenant.objects.filter(entreprise=self.entreprise, nom="Mavungu", prenom="Alice").exists())

    def test_gestionnaire_can_create_formation(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("formation_create"),
            {
                "nom": "Bureautique",
                "description": "Suite office",
                "prix": "125.00",
                "duree": "2 mois",
                "actif": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Formation.objects.filter(entreprise=self.entreprise, nom="Bureautique").exists())

    def test_gestionnaire_can_update_formation(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("formation_update", args=[self.formation.id]),
            {
                "nom": "Excel avance",
                "description": "Version avancee",
                "prix": "85.00",
                "duree": "6 semaines",
                "actif": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.formation.refresh_from_db()
        self.assertEqual(self.formation.nom, "Excel avance")
        self.assertEqual(self.formation.prix, Decimal("85.00"))

    def test_gestionnaire_can_toggle_formation_status(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(reverse("formation_toggle_status", args=[self.formation.id]))

        self.assertEqual(response.status_code, 302)
        self.formation.refresh_from_db()
        self.assertFalse(self.formation.actif)

    def test_gestionnaire_cannot_update_other_entreprise_formation(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("formation_update", args=[self.formation_externe.id]))
        self.assertEqual(response.status_code, 404)

    def test_comptable_cannot_manage_formations(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("formation_create"))
        self.assertEqual(response.status_code, 403)

    def test_gestionnaire_can_create_inscription(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("inscription_create"),
            {
                "apprenant": self.apprenant.id,
                "formation": Formation.objects.create(
                    entreprise=self.entreprise,
                    nom="Word",
                    prix=Decimal("50.00"),
                ).id,
                "statut": InscriptionFormation.Statut.EN_COURS,
                "montant_prevu": "50.00",
            },
        )

        self.assertEqual(response.status_code, 302)
        inscription = InscriptionFormation.objects.get(entreprise=self.entreprise, apprenant=self.apprenant, formation__nom="Word")
        self.assertEqual(inscription.montant_paye, Decimal("0.00"))
        self.assertEqual(inscription.solde, Decimal("50.00"))
        self.assertEqual(inscription.statut_paiement, InscriptionFormation.StatutPaiement.IMPAYE)

    def test_inscription_view_does_not_store_posted_initial_payment(self):
        self.client.force_login(self.gestionnaire)
        formation = Formation.objects.create(
            entreprise=self.entreprise,
            nom="Excel",
            prix=Decimal("50.00"),
        )
        response = self.client.post(
            reverse("inscription_create"),
            {
                "apprenant": self.apprenant.id,
                "formation": formation.id,
                "statut": InscriptionFormation.Statut.EN_COURS,
                "montant_prevu": "50.00",
                "montant_paye": "60.00",
            },
        )

        self.assertEqual(response.status_code, 302)
        inscription = InscriptionFormation.objects.get(
            entreprise=self.entreprise,
            apprenant=self.apprenant,
            formation=formation,
            montant_prevu=Decimal("50.00"),
        )
        self.assertEqual(inscription.montant_paye, Decimal("0.00"))
        self.assertEqual(inscription.solde, Decimal("50.00"))
        self.assertFalse(PaiementInscription.objects.filter(inscription=inscription).exists())

    def test_comptable_cannot_manage_inscriptions(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("inscription_create"))
        self.assertEqual(response.status_code, 403)

    def test_comptable_can_view_inscription_detail(self):
        PaiementInscription.objects.create(
            entreprise=self.entreprise,
            inscription=self.inscription,
            montant=Decimal("25.00"),
            utilisateur=self.gestionnaire,
        )
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("inscription_detail", args=[self.inscription.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lema")

    def test_gestionnaire_can_update_inscription_expected_amount(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("inscription_update_montant_prevu", args=[self.inscription.id]),
            {"montant_prevu": "60.00"},
        )

        self.assertEqual(response.status_code, 302)
        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_prevu, Decimal("60.00"))
        self.assertEqual(self.inscription.montant_paye, Decimal("25.00"))
        self.assertEqual(self.inscription.solde, Decimal("35.00"))

    def test_comptable_cannot_update_inscription_expected_amount(self):
        self.client.force_login(self.comptable)
        response = self.client.post(
            reverse("inscription_update_montant_prevu", args=[self.inscription.id]),
            {"montant_prevu": "60.00"},
        )

        self.assertEqual(response.status_code, 403)

    def test_gestionnaire_can_create_paiement(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("paiement_inscription_create", args=[self.inscription.id]),
            {
                "montant": "30.00",
                "mode_paiement": PaiementInscription.ModePaiement.ESPECES,
                "reference": "APR-30",
                "observations": "Versement initial",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_paye, Decimal("55.00"))
        self.assertEqual(self.inscription.solde, Decimal("20.00"))

    def test_paiement_view_allows_amount_greater_than_remaining_balance(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("paiement_inscription_create", args=[self.inscription.id]),
            {
                "montant": "51.00",
                "mode_paiement": PaiementInscription.ModePaiement.ESPECES,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_paye, Decimal("76.00"))
        self.assertEqual(self.inscription.solde, Decimal("0.00"))
        self.assertEqual(self.inscription.trop_percu, Decimal("1.00"))

    def test_inscription_detail_shows_receipt_and_quittance_actions(self):
        receipt_payment = self.inscription.paiements.order_by("id").first()
        clearance_payment = PaiementInscription.objects.create(
            entreprise=self.entreprise,
            inscription=self.inscription,
            montant=Decimal("50.00"),
            utilisateur=self.gestionnaire,
        )
        self.client.force_login(self.gestionnaire)

        response = self.client.get(reverse("inscription_detail", args=[self.inscription.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Télécharger le reçu")
        self.assertContains(response, "Télécharger la quittance")
        self.assertContains(
            response,
            reverse("paiement_inscription_document_pdf", args=[self.inscription.id, receipt_payment.id]),
        )
        self.assertContains(
            response,
            reverse("paiement_inscription_document_pdf", args=[self.inscription.id, clearance_payment.id]),
        )

    def test_partial_payment_document_returns_receipt_pdf(self):
        paiement = self.inscription.paiements.order_by("id").first()
        self.client.force_login(self.gestionnaire)

        response = self.client.get(
            reverse("paiement_inscription_document_pdf", args=[self.inscription.id, paiement.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("recu.pdf", response["Content-Disposition"])
        self.assertNotIn("quittance.pdf", response["Content-Disposition"])

    def test_settling_payment_document_returns_quittance_pdf(self):
        paiement = PaiementInscription.objects.create(
            entreprise=self.entreprise,
            inscription=self.inscription,
            montant=Decimal("50.00"),
            utilisateur=self.gestionnaire,
        )
        self.client.force_login(self.gestionnaire)

        response = self.client.get(
            reverse("paiement_inscription_document_pdf", args=[self.inscription.id, paiement.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("quittance.pdf", response["Content-Disposition"])

    def test_overpaid_payment_document_returns_quittance_pdf(self):
        paiement = PaiementInscription.objects.create(
            entreprise=self.entreprise,
            inscription=self.inscription,
            montant=Decimal("51.00"),
            utilisateur=self.gestionnaire,
        )
        self.client.force_login(self.gestionnaire)

        response = self.client.get(
            reverse("paiement_inscription_document_pdf", args=[self.inscription.id, paiement.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("quittance.pdf", response["Content-Disposition"])

    def test_paiement_view_refuses_unknown_payment_mode(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("paiement_inscription_create", args=[self.inscription.id]),
            {
                "montant": "10.00",
                "mode_paiement": "crypto",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Le mode de paiement est invalide.", status_code=400)
        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.montant_paye, Decimal("25.00"))
        self.assertEqual(self.inscription.solde, Decimal("50.00"))

    def test_gestionnaire_cannot_access_other_entreprise_payment_url(self):
        self.client.force_login(self.gestionnaire)

        get_response = self.client.get(reverse("paiement_inscription_create", args=[self.inscription_externe.id]))
        post_response = self.client.post(
            reverse("paiement_inscription_create", args=[self.inscription_externe.id]),
            {
                "montant": "10.00",
                "mode_paiement": PaiementInscription.ModePaiement.ESPECES,
            },
        )

        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(post_response.status_code, 404)
        self.inscription_externe.refresh_from_db()
        self.assertEqual(self.inscription_externe.montant_paye, Decimal("0.00"))
        self.assertEqual(self.inscription_externe.solde, Decimal("150.00"))

    def test_comptable_can_access_paiement_form(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("paiement_inscription_create", args=[self.inscription.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enregistrer un paiement")

    def test_paiement_form_shows_document_action_for_existing_payment(self):
        paiement = self.inscription.paiements.order_by("id").first()
        self.client.force_login(self.gestionnaire)

        response = self.client.get(reverse("paiement_inscription_create", args=[self.inscription.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Télécharger le reçu")
        self.assertContains(
            response,
            reverse("paiement_inscription_document_pdf", args=[self.inscription.id, paiement.id]),
        )

    def test_dashboard_filters_by_formation(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(
            reverse("apprenants_dashboard"),
            {"formation": self.formation.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lema")
        self.assertNotContains(response, "Mbala")

    def test_dashboard_filters_by_statut(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(
            reverse("apprenants_dashboard"),
            {"statut": InscriptionFormation.Statut.TERMINEE},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mbala")
        self.assertNotContains(response, "Lema")

    def test_dashboard_alerts_are_scoped_to_current_entreprise(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("apprenants_dashboard"))

        oldest_unpaid = list(response.context["alerts"]["oldest_unpaid_inscriptions"])
        self.assertEqual(oldest_unpaid, [self.inscription])

    def test_gestionnaire_can_generate_facture_from_inscription(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(reverse("inscription_generate_facture", args=[self.inscription.id]))

        self.assertEqual(response.status_code, 302)
        self.inscription.refresh_from_db()
        self.assertIsNotNone(self.inscription.facture_id)
        self.assertTrue(Facture.objects.filter(id=self.inscription.facture_id, entreprise=self.entreprise).exists())

    def test_generate_facture_action_is_not_available_to_comptable(self):
        self.client.force_login(self.comptable)
        response = self.client.post(reverse("inscription_generate_facture", args=[self.inscription.id]))
        self.assertEqual(response.status_code, 403)

    def test_inscription_detail_displays_linked_facture(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("75.00"),
        )
        self.inscription.facture = facture
        self.inscription.save(update_fields=["facture"])

        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("inscription_detail", args=[self.inscription.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, facture.numero)
        self.assertContains(response, reverse("facture_detail", args=[facture.id]))

    def test_gestionnaire_can_link_existing_facture_to_inscription(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("75.00"),
        )
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("inscription_link_existing_facture", args=[self.inscription.id]),
            {"facture_id": facture.id},
        )

        self.assertEqual(response.status_code, 302)
        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.facture_id, facture.id)

    def test_link_existing_facture_action_is_not_available_to_comptable(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("75.00"),
        )
        self.client.force_login(self.comptable)
        response = self.client.post(
            reverse("inscription_link_existing_facture", args=[self.inscription.id]),
            {"facture_id": facture.id},
        )
        self.assertEqual(response.status_code, 403)

    def test_inscription_detail_displays_manual_link_mode(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("75.00"),
        )
        self.client.force_login(self.gestionnaire)
        self.client.post(
            reverse("inscription_link_existing_facture", args=[self.inscription.id]),
            {"facture_id": facture.id},
        )

        response = self.client.get(reverse("inscription_detail", args=[self.inscription.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Liee manuellement")

    def test_inscription_detail_shows_unlink_action_when_facture_is_linked(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("75.00"),
        )
        self.inscription.facture = facture
        self.inscription.save(update_fields=["facture"])

        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("inscription_detail", args=[self.inscription.id]))
        self.assertContains(response, "Delier la facture")

    def test_gestionnaire_can_unlink_facture_from_inscription(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("75.00"),
            statut=Facture.Statut.EMISE,
        )
        self.inscription.facture = facture
        self.inscription.save(update_fields=["facture"])

        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("inscription_unlink_facture", args=[self.inscription.id]),
            {"facture_id": facture.id},
        )

        self.assertEqual(response.status_code, 302)
        self.inscription.refresh_from_db()
        self.assertIsNone(self.inscription.facture_id)

    def test_unlink_facture_action_is_not_available_to_comptable(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("75.00"),
        )
        self.inscription.facture = facture
        self.inscription.save(update_fields=["facture"])

        self.client.force_login(self.comptable)
        response = self.client.post(
            reverse("inscription_unlink_facture", args=[self.inscription.id]),
            {"facture_id": facture.id},
        )
        self.assertEqual(response.status_code, 403)

    def test_inscription_detail_no_longer_displays_facture_after_unlink(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom=str(self.apprenant),
            montant=Decimal("75.00"),
            statut=Facture.Statut.EMISE,
        )
        self.inscription.facture = facture
        self.inscription.save(update_fields=["facture"])

        self.client.force_login(self.gestionnaire)
        self.client.post(
            reverse("inscription_unlink_facture", args=[self.inscription.id]),
            {"facture_id": facture.id},
        )
        response = self.client.get(reverse("inscription_detail", args=[self.inscription.id]))
        self.assertContains(response, "Aucune facture liee")

    def test_inscription_detail_displays_billing_history(self):
        self.client.force_login(self.gestionnaire)
        self.client.post(reverse("inscription_generate_facture", args=[self.inscription.id]))
        response = self.client.get(reverse("inscription_detail", args=[self.inscription.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Historique de liaison facturation")
        self.assertContains(response, "facture_inscription_creee")

    def test_inscription_billing_history_selector_is_robust_with_missing_metadata(self):
        ActivityLog.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.gestionnaire,
            action="facture_existante_liee_inscription",
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=self.inscription.id,
            description="Facture liee sans metadata.",
            metadata={},
        )

        history = get_inscription_billing_history(self.inscription)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["facture_numero"], "")

    def test_inscription_billing_history_is_sorted_from_most_recent_to_oldest(self):
        ActivityLog.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.gestionnaire,
            action="facture_inscription_creee",
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=self.inscription.id,
            description="Creation.",
            metadata={"facture_numero": "F-0001"},
        )
        ActivityLog.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.gestionnaire,
            action="facture_deliee_inscription",
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=self.inscription.id,
            description="Deliage.",
            metadata={"facture_numero": "F-0001"},
        )

        history = get_inscription_billing_history(self.inscription)
        self.assertEqual([entry["action"] for entry in history], ["facture_deliee_inscription", "facture_inscription_creee"])


class ApprenantsExportViewsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Export")
        self.autre_entreprise = create_entreprise("Entreprise Export B")
        self.gestionnaire = create_user("gestion-export", "gestionnaire", self.entreprise)
        self.comptable = create_user("compta-export", "comptable", self.entreprise)
        self.plan = Abonnement.objects.create(
            nom="Apprenants Exports",
            code="appr-exports",
            prix=24,
            duree_jours=30,
            actif=True,
            modules_inclus=["apprenants"],
        )
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.gestionnaire)
        self.apprenant = Apprenant.objects.create(
            entreprise=self.entreprise,
            nom="Lukusa",
            prenom="Anne",
            telephone="+243999",
            email="anne@example.com",
        )
        self.apprenant_externe = Apprenant.objects.create(
            entreprise=self.autre_entreprise,
            nom="Externe",
            prenom="Paul",
        )
        self.formation = Formation.objects.create(
            entreprise=self.entreprise,
            nom="Excel",
            prix=Decimal("200.00"),
            actif=True,
        )
        self.formation_externe = Formation.objects.create(
            entreprise=self.autre_entreprise,
            nom="Formation Externe",
            prix=Decimal("300.00"),
            actif=True,
        )
        self.inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise,
            apprenant=self.apprenant,
            formation=self.formation,
            statut=InscriptionFormation.Statut.EN_COURS,
            montant_prevu=Decimal("200.00"),
            montant_paye=Decimal("80.00"),
            solde=Decimal("120.00"),
        )
        self.inscription_externe = InscriptionFormation.objects.create(
            entreprise=self.autre_entreprise,
            apprenant=self.apprenant_externe,
            formation=self.formation_externe,
            statut=InscriptionFormation.Statut.EN_COURS,
            montant_prevu=Decimal("300.00"),
            montant_paye=Decimal("0.00"),
            solde=Decimal("300.00"),
        )
        self.paiement = PaiementInscription.objects.create(
            entreprise=self.entreprise,
            inscription=self.inscription,
            montant=Decimal("80.00"),
            utilisateur=self.gestionnaire,
            reference="PAY-EXP-1",
        )

    def _extract_sheet_xml(self, response):
        with ZipFile(BytesIO(response.content)) as archive:
            return archive.read("xl/worksheets/sheet1.xml").decode("utf-8")

    def test_comptable_can_access_exports_with_view_permission(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("apprenants_excel"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_apprenants_excel_is_scoped_to_entreprise(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("apprenants_excel"))

        sheet_xml = self._extract_sheet_xml(response)
        self.assertIn("Lukusa", sheet_xml)
        self.assertNotIn("Externe", sheet_xml)

    def test_inscriptions_excel_respects_filters(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(
            reverse("inscriptions_excel"),
            {"formation": self.formation.id, "statut": InscriptionFormation.Statut.EN_COURS},
        )

        sheet_xml = self._extract_sheet_xml(response)
        self.assertIn("Lukusa Anne", sheet_xml)
        self.assertIn("Excel", sheet_xml)
        self.assertNotIn("Formation Externe", sheet_xml)

    def test_paiements_excel_contains_expected_payment_history(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("inscription_paiements_excel", args=[self.inscription.id]))

        sheet_xml = self._extract_sheet_xml(response)
        self.assertIn("PAY-EXP-1", sheet_xml)
        self.assertIn("80.00", sheet_xml)

    def test_pdf_export_returns_pdf_response(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("apprenants_pdf"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("apprenants.pdf", response["Content-Disposition"])

    def test_dashboard_excel_export_respects_current_filters(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(
            reverse("apprenants_dashboard_excel"),
            {"formation": self.formation.id, "statut": InscriptionFormation.Statut.EN_COURS},
        )

        sheet_xml = self._extract_sheet_xml(response)
        self.assertIn("Total inscriptions", sheet_xml)
        self.assertIn(">1<", sheet_xml)
