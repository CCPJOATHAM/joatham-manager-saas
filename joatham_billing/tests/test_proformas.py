from decimal import Decimal
from unittest.mock import patch

from django.http import Http404, HttpResponse
from django.test import TestCase
from django.urls import reverse

from core.services.subscription import activate_subscription_for_entreprise
from joatham_dashboard.selectors.dashboard import get_dashboard_kpis_by_entreprise
from joatham_products.models import Produit, StockMovement
from joatham_users.models import Abonnement

from .factories import create_client, create_entreprise, create_user
from ..exceptions import PermissionFacturationError, WorkflowFacturationError
from ..models import Facture, PaiementFacture, Proforma, Service
from ..selectors.billing import get_factures_by_entreprise, get_proforma_by_entreprise, get_proformas_by_entreprise
from ..services.proforma import create_proforma, convert_proforma_to_facture


class ProformaWorkflowTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Proforma")
        self.autre_entreprise = create_entreprise("Entreprise Proforma B")
        self.owner = create_user("owner-proforma", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("manager-proforma", "gestionnaire", self.entreprise)
        self.comptable = create_user("accountant-proforma", "comptable", self.entreprise)
        self.owner_b = create_user("owner-proforma-b", "proprietaire", self.autre_entreprise)
        self.plan = Abonnement.objects.create(nom="Premium", code="premium", prix=20, duree_jours=30, actif=True)
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.owner)
        activate_subscription_for_entreprise(entreprise=self.autre_entreprise, plan=self.plan, utilisateur=self.owner_b)
        self.client_billing = create_client(self.entreprise, "Client Proforma")
        self.client_b = create_client(self.autre_entreprise, "Client externe")
        self.service = Service.objects.create(
            entreprise=self.entreprise,
            nom="Conseil commercial",
            prix=Decimal("40.00"),
            actif=True,
        )
        self.product = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Papier A4",
            description="Rame papier A4",
            reference="RAM-A4",
            prix_unitaire=Decimal("12.00"),
            quantite_stock=10,
            seuil_alerte=2,
            actif=True,
        )
        self.product_b = Produit.objects.create(
            entreprise=self.autre_entreprise,
            nom="Produit externe",
            description="Produit externe",
            reference="EXT-PROF",
            prix_unitaire=Decimal("15.00"),
            quantite_stock=8,
            seuil_alerte=1,
            actif=True,
        )

    def _lines(self, quantity="2", price=""):
        return [
            {
                "product_id": str(self.product.id),
                "service_id": "",
                "designation": "",
                "quantite": quantity,
                "prix": price,
            }
        ]

    def _create_proforma(self, *, user=None, lines=None):
        return create_proforma(
            entreprise=self.entreprise,
            user=user or self.owner,
            client_id=self.client_billing.id,
            client_nom="",
            tva=0,
            remise=0,
            rabais=0,
            ristourne=0,
            lignes=lines or self._lines(),
        )

    def test_create_proforma_success_without_facture(self):
        proforma = self._create_proforma()

        self.assertTrue(proforma.numero.startswith("PF-"))
        self.assertEqual(proforma.client_id, self.client_billing.id)
        self.assertEqual(proforma.lignes.count(), 1)
        self.assertEqual(proforma.total_net, Decimal("24.00"))
        self.assertEqual(Facture.objects.filter(entreprise=self.entreprise).count(), 0)

    def test_create_proforma_does_not_decrement_stock(self):
        proforma = self._create_proforma()

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 10)
        self.assertEqual(proforma.total_net, Decimal("24.00"))
        self.assertFalse(
            StockMovement.objects.filter(
                entreprise=self.entreprise,
                produit=self.product,
                movement_type=StockMovement.MovementType.INVOICE_SALE,
            ).exists()
        )

    def test_proforma_absent_from_facture_selectors_and_dashboard_revenue(self):
        self._create_proforma()

        self.assertEqual(list(get_factures_by_entreprise(self.entreprise)), [])
        kpis = get_dashboard_kpis_by_entreprise(self.entreprise)
        self.assertEqual(kpis["nombre_factures"], 0)
        self.assertEqual(kpis["total_ca"], Decimal("0"))
        self.assertEqual(kpis["total_encaisse"], Decimal("0"))

    def test_proforma_is_not_payable_from_detail(self):
        proforma = self._create_proforma()
        self.client.force_login(self.owner)

        response = self.client.get(reverse("proforma_detail", args=[proforma.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucun paiement n'est enregistre")
        self.assertNotContains(response, "Enregistrer un paiement")
        self.assertEqual(PaiementFacture.objects.count(), 0)

    def test_proforma_pdf_uses_dedicated_template(self):
        proforma = self._create_proforma()
        self.client.force_login(self.owner)

        with patch("joatham_billing.views.render_pdf_response") as render_pdf_response:
            render_pdf_response.return_value = HttpResponse(b"PDF", content_type="application/pdf")
            response = self.client.get(reverse("proforma_pdf", args=[proforma.id]))

        self.assertEqual(response.status_code, 200)
        render_pdf_response.assert_called_once()
        self.assertEqual(render_pdf_response.call_args.args[1], "joatham_billing/proforma_pdf.html")
        self.assertEqual(render_pdf_response.call_args.kwargs["filename"], f"proforma_{proforma.numero}.pdf")

    def test_convert_proforma_creates_real_facture_and_applies_stock(self):
        proforma = self._create_proforma()

        facture = convert_proforma_to_facture(proforma=proforma, user=self.owner)

        proforma.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(proforma.statut, Proforma.Statut.CONVERTIE)
        self.assertEqual(proforma.facture_convertie_id, facture.id)
        self.assertTrue(facture.numero.startswith("F-"))
        self.assertEqual(facture.client_id, proforma.client_id)
        self.assertEqual(facture.lignes.count(), 1)
        self.assertEqual(facture.total_net, proforma.total_net)
        self.assertEqual(self.product.quantite_stock, 8)
        self.assertTrue(facture.stock_applique)
        self.assertTrue(
            StockMovement.objects.filter(
                entreprise=self.entreprise,
                produit=self.product,
                movement_type=StockMovement.MovementType.INVOICE_SALE,
                source_app="joatham_billing",
                source_model="Facture",
                source_id=facture.id,
            ).exists()
        )

    def test_convert_proforma_does_not_create_payment_and_blocks_second_conversion(self):
        proforma = self._create_proforma()
        facture = convert_proforma_to_facture(proforma=proforma, user=self.owner)

        self.assertEqual(PaiementFacture.objects.filter(facture=facture).count(), 0)
        with self.assertRaises(WorkflowFacturationError):
            convert_proforma_to_facture(proforma=proforma, user=self.owner)

    def test_proforma_selectors_are_scoped_to_entreprise(self):
        proforma = self._create_proforma()
        other_proforma = create_proforma(
            entreprise=self.autre_entreprise,
            user=self.owner_b,
            client_id=self.client_b.id,
            tva=0,
            lignes=[
                {
                    "product_id": str(self.product_b.id),
                    "service_id": "",
                    "designation": "",
                    "quantite": 1,
                    "prix": "",
                }
            ],
        )

        self.assertEqual(list(get_proformas_by_entreprise(self.entreprise)), [proforma])
        with self.assertRaises(Http404):
            get_proforma_by_entreprise(self.entreprise, other_proforma.id)

    def test_cross_tenant_proforma_detail_is_blocked(self):
        other_proforma = create_proforma(
            entreprise=self.autre_entreprise,
            user=self.owner_b,
            client_id=self.client_b.id,
            tva=0,
            lignes=[
                {
                    "product_id": str(self.product_b.id),
                    "service_id": "",
                    "designation": "",
                    "quantite": 1,
                    "prix": "",
                }
            ],
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("proforma_detail", args=[other_proforma.id]))

        self.assertEqual(response.status_code, 404)

    def test_view_and_manage_permissions_are_respected(self):
        proforma = self._create_proforma()
        self.client.force_login(self.comptable)

        list_response = self.client.get(reverse("proforma_list"))
        detail_response = self.client.get(reverse("proforma_detail", args=[proforma.id]))
        add_response = self.client.get(reverse("add_proforma"))

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(add_response.status_code, 403)
        self.assertNotContains(detail_response, "Convertir en facture")
        with self.assertRaises(PermissionFacturationError):
            create_proforma(
                entreprise=self.entreprise,
                user=self.comptable,
                client_id=self.client_billing.id,
                tva=0,
                lignes=self._lines(),
            )

    def test_gestionnaire_can_create_and_convert_proforma(self):
        proforma = self._create_proforma(user=self.gestionnaire)

        facture = convert_proforma_to_facture(proforma=proforma, user=self.gestionnaire)

        self.assertEqual(facture.entreprise_id, self.entreprise.id)
        self.assertEqual(Facture.objects.filter(entreprise=self.entreprise).count(), 1)

    def test_cancelled_proforma_cannot_be_converted(self):
        proforma = self._create_proforma()
        proforma.statut = Proforma.Statut.ANNULEE
        proforma.save(update_fields=["statut"])

        with self.assertRaises(WorkflowFacturationError):
            convert_proforma_to_facture(proforma=proforma, user=self.owner)

    def test_proforma_form_and_list_views_render(self):
        self.client.force_login(self.owner)
        proforma = self._create_proforma()

        list_response = self.client.get(reverse("proforma_list"))
        add_response = self.client.get(reverse("add_proforma"))
        edit_response = self.client.get(reverse("edit_proforma", args=[proforma.id]))

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, proforma.numero)
        self.assertEqual(add_response.status_code, 200)
        self.assertContains(add_response, "Nouvelle facture proforma")
        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(edit_response, "Modifier la facture proforma")

    def test_post_create_proforma_from_view(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("add_proforma"),
            {
                "client": str(self.client_billing.id),
                "client_nom": "",
                "tva": "0",
                "remise": "0",
                "rabais": "0",
                "ristourne": "0",
                "product_id[]": [str(self.product.id)],
                "service_id[]": [""],
                "designation[]": [""],
                "quantite[]": ["2"],
                "prix[]": [""],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Proforma.objects.filter(entreprise=self.entreprise).count(), 1)
        self.assertEqual(Facture.objects.filter(entreprise=self.entreprise).count(), 0)

    def test_post_convert_proforma_from_view(self):
        proforma = self._create_proforma()
        self.client.force_login(self.owner)

        response = self.client.post(reverse("convert_proforma", args=[proforma.id]))

        self.assertEqual(response.status_code, 302)
        facture = Facture.objects.get(entreprise=self.entreprise)
        self.assertEqual(response["Location"], reverse("facture_detail", args=[facture.id]))
        proforma.refresh_from_db()
        self.assertEqual(proforma.facture_convertie_id, facture.id)
        self.assertEqual(PaiementFacture.objects.filter(facture=facture).count(), 0)
