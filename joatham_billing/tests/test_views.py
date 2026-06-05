from decimal import Decimal
from unittest.mock import patch

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from core.services.subscription import activate_subscription_for_entreprise
from joatham_caisse.models import Caisse, MouvementCaisse, SessionCaisse
from joatham_billing.models import EntreprisePrintSettings, Facture, PaiementFacture, Service
from joatham_billing.views import _build_facture_context
from joatham_products.models import Produit
from joatham_users.models import Abonnement

from .factories import create_client, create_entreprise, create_facture_sample, create_user


class BillingViewsPremiumTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Premium")
        self.user = create_user("owner-premium", "proprietaire", self.entreprise)
        self.plan = Abonnement.objects.create(
            nom="Premium",
            code="premium-billing",
            prix=49,
            duree_jours=30,
            actif=True,
        )
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.user)
        self.client_billing = create_client(self.entreprise, "Client Premium")
        self.service = Service.objects.create(
            entreprise=self.entreprise,
            nom="Audit express",
            prix=Decimal("125.00"),
            actif=True,
        )
        self.product = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Ordinateur portable",
            description="Ordinateur portable professionnel",
            reference="PC-01",
            prix_unitaire=Decimal("900.00"),
            quantite_stock=3,
            seuil_alerte=2,
            actif=True,
        )
        self.facture = create_facture_sample(self.entreprise, self.user, self.client_billing)
        self.caisse = Caisse.objects.create(
            entreprise=self.entreprise,
            nom="Caisse premium",
            code="CP-01",
            est_active=True,
            cree_par=self.user,
        )
        self.session_caisse = SessionCaisse.objects.create(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur_ouverture=self.user,
            solde_initial=Decimal("100.00"),
        )
        self.client.force_login(self.user)

    def render_a4_facture_html(self, facture):
        context = _build_facture_context(facture, mode=None)
        html = render_to_string("joatham_billing/facture_pdf.html", context)
        return html, context

    def test_facture_list_displays_premium_sections(self):
        response = self.client.get(reverse("facture_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Facturation")
        self.assertContains(response, "Montant facture")
        self.assertContains(response, "Montant encaisse")
        self.assertContains(response, "Reste a encaisser")
        self.assertContains(response, "Imprimer A4")
        self.assertContains(response, "Imprimer POS")
        self.assertContains(response, self.facture.numero)

    def test_facture_detail_displays_redesigned_sections(self):
        response = self.client.get(reverse("facture_detail", args=[self.facture.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Prestations facturees")
        self.assertContains(response, "Enregistrer un paiement")
        self.assertContains(response, "Historique")
        self.assertContains(response, "Imprimer A4")
        self.assertContains(response, "Imprimer POS")
        self.assertContains(response, self.facture.numero)

    def test_facture_detail_exposes_optional_caisse_field_for_payment(self):
        response = self.client.get(reverse("facture_detail", args=[self.facture.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="caisse"')
        self.assertContains(response, self.caisse.nom)

    def test_facture_detail_displays_line_origin_badges(self):
        self.facture.statut = Facture.Statut.BROUILLON
        self.facture.paye = False
        self.facture.save(update_fields=["statut", "paye"])
        self.facture.lignes.all().delete()
        self.facture.lignes.create(
            produit=self.product,
            designation=self.product.description,
            quantite=1,
            prix_unitaire=self.product.prix_unitaire,
            tva=self.facture.tva,
        )
        self.facture.lignes.create(
            service=self.service,
            designation=self.service.nom,
            quantite=1,
            prix_unitaire=self.service.prix,
            tva=self.facture.tva,
        )
        self.facture.lignes.create(
            designation="Ligne libre speciale",
            quantite=1,
            prix_unitaire=Decimal("10.00"),
            tva=self.facture.tva,
        )

        response = self.client.get(reverse("facture_detail", args=[self.facture.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Produit")
        self.assertContains(response, "Service")
        self.assertContains(response, "Saisie libre")
        self.assertContains(response, self.product.nom)
        self.assertContains(response, self.service.nom)

    def test_facture_pdf_still_renders_successfully(self):
        response = self.client.get(reverse("facture_pdf", args=[self.facture.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_facture_a4_pdf_displays_unpaid_payment_summary(self):
        html, context = self.render_a4_facture_html(self.facture)

        self.assertEqual(self.facture.total_paye, Decimal("0"))
        self.assertEqual(self.facture.reste_a_payer, self.facture.total_net)
        self.assertIn("TOTAL NET", html)
        self.assertIn("Montant paye", html)
        self.assertIn("Reste a payer", html)
        self.assertIn(context["summary"]["total_paye"], html)
        self.assertIn(context["summary"]["reste_a_payer"], html)

    def test_facture_a4_pdf_displays_partial_payment_summary(self):
        PaiementFacture.objects.create(
            facture=self.facture,
            montant=Decimal("25.00"),
            mode=PaiementFacture.ModePaiement.ESPECES,
            reference="PART-001",
        )
        self.facture.refresh_from_db()

        html, context = self.render_a4_facture_html(self.facture)

        self.assertEqual(self.facture.total_paye, Decimal("25.00"))
        self.assertEqual(self.facture.reste_a_payer, self.facture.total_net - Decimal("25.00"))
        self.assertIn("Montant paye", html)
        self.assertIn("Reste a payer", html)
        self.assertIn(context["summary"]["total_paye"], html)
        self.assertIn(context["summary"]["reste_a_payer"], html)

    def test_facture_a4_pdf_displays_paid_payment_summary(self):
        PaiementFacture.objects.create(
            facture=self.facture,
            montant=self.facture.total_net,
            mode=PaiementFacture.ModePaiement.ESPECES,
            reference="FULL-001",
        )
        self.facture.refresh_from_db()

        html, context = self.render_a4_facture_html(self.facture)

        self.assertEqual(self.facture.reste_a_payer, Decimal("0"))
        self.assertIn("Montant paye", html)
        self.assertIn("Reste a payer", html)
        self.assertIn(context["summary"]["total_paye"], html)
        self.assertIn(context["summary"]["reste_a_payer"], html)

    def test_facture_pos_pdf_renders_successfully(self):
        response = self.client.get(reverse("facture_pdf", args=[self.facture.id]) + "?format=pos")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_pos_print_settings_are_created_automatically(self):
        self.assertFalse(EntreprisePrintSettings.objects.filter(entreprise=self.entreprise).exists())

        with patch("joatham_billing.views.render_pdf_response") as render_pdf_response:
            render_pdf_response.return_value = HttpResponse(b"PDF", content_type="application/pdf")
            response = self.client.get(reverse("facture_pdf", args=[self.facture.id]) + "?format=pos")

        self.assertEqual(response.status_code, 200)
        print_settings = EntreprisePrintSettings.objects.get(entreprise=self.entreprise)
        context = render_pdf_response.call_args.args[2]
        self.assertEqual(print_settings.pos_width, EntreprisePrintSettings.POSWidth.WIDTH_80)
        self.assertEqual(context["pos_ticket"]["page_width"], "80mm")
        self.assertEqual(context["pos_ticket"]["content_width"], "72mm")

    def test_facture_pdf_default_uses_a4_template(self):
        with patch("joatham_billing.views.render_pdf_response") as render_pdf_response:
            render_pdf_response.return_value = HttpResponse(b"PDF", content_type="application/pdf")

            response = self.client.get(reverse("facture_pdf", args=[self.facture.id]))

        self.assertEqual(response.status_code, 200)
        render_pdf_response.assert_called_once()
        self.assertEqual(render_pdf_response.call_args.args[1], "joatham_billing/facture_pdf.html")
        self.assertEqual(render_pdf_response.call_args.kwargs["filename"], f"facture_{self.facture.numero}.pdf")

    def test_facture_pdf_uses_company_default_pos_when_configured(self):
        EntreprisePrintSettings.objects.create(
            entreprise=self.entreprise,
            default_invoice_format=EntreprisePrintSettings.InvoiceFormat.POS,
        )

        with patch("joatham_billing.views.render_pdf_response") as render_pdf_response:
            render_pdf_response.return_value = HttpResponse(b"PDF", content_type="application/pdf")
            response = self.client.get(reverse("facture_pdf", args=[self.facture.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(render_pdf_response.call_args.args[1], "joatham_billing/facture_pos_pdf.html")
        self.assertEqual(render_pdf_response.call_args.kwargs["filename"], f"ticket_{self.facture.numero}.pdf")

    def test_facture_pos_pdf_uses_58mm_when_configured(self):
        EntreprisePrintSettings.objects.create(
            entreprise=self.entreprise,
            pos_width=EntreprisePrintSettings.POSWidth.WIDTH_58,
        )

        with patch("joatham_billing.views.render_pdf_response") as render_pdf_response:
            render_pdf_response.return_value = HttpResponse(b"PDF", content_type="application/pdf")
            response = self.client.get(reverse("facture_pdf", args=[self.facture.id]) + "?format=pos")

        self.assertEqual(response.status_code, 200)
        context = render_pdf_response.call_args.args[2]
        self.assertEqual(context["pos_ticket"]["page_width"], "58mm")
        self.assertEqual(context["pos_ticket"]["content_width"], "50mm")

    def test_facture_pdf_pos_uses_ticket_template_and_payment_totals(self):
        PaiementFacture.objects.create(
            facture=self.facture,
            montant=Decimal("25.00"),
            mode=PaiementFacture.ModePaiement.MOBILE_MONEY,
            reference="MM-001",
        )

        with patch("joatham_billing.views.render_pdf_response") as render_pdf_response:
            render_pdf_response.return_value = HttpResponse(b"PDF", content_type="application/pdf")

            response = self.client.get(reverse("facture_pdf", args=[self.facture.id]) + "?format=pos")

        self.assertEqual(response.status_code, 200)
        render_pdf_response.assert_called_once()
        template_name = render_pdf_response.call_args.args[1]
        context = render_pdf_response.call_args.args[2]
        self.assertEqual(template_name, "joatham_billing/facture_pos_pdf.html")
        self.assertEqual(render_pdf_response.call_args.kwargs["filename"], f"ticket_{self.facture.numero}.pdf")
        self.assertEqual(context["latest_payment_mode"], "Mobile Money")
        self.assertIn("25", context["summary"]["total_paye"])
        self.assertIn("91", context["summary"]["reste_a_payer"])

    def test_facture_pos_template_hides_logo_tax_info_and_generated_by(self):
        self.entreprise.rccm = "RCCM-001"
        self.entreprise.numero_impot = "NIF-001"
        self.entreprise.id_nat = "IDNAT-001"
        self.entreprise.save(update_fields=["rccm", "numero_impot", "id_nat"])
        print_settings = EntreprisePrintSettings.objects.create(
            entreprise=self.entreprise,
            pos_show_logo=False,
            pos_show_tax_info=False,
            pos_show_generated_by=False,
        )
        context = _build_facture_context(self.facture, mode=None, print_settings=print_settings)
        context["legal_information"]["logo_data_uri"] = "data:image/png;base64,abc"

        html = render_to_string("joatham_billing/facture_pos_pdf.html", context)

        self.assertNotIn('class="ticket-logo"', html)
        self.assertNotIn("RCCM-001", html)
        self.assertNotIn("NIF-001", html)
        self.assertNotIn("IDNAT-001", html)
        self.assertNotIn("Genere par JOATHAM Manager", html)

    def test_facture_pos_template_displays_custom_footer(self):
        print_settings = EntreprisePrintSettings.objects.create(
            entreprise=self.entreprise,
            pos_footer_message="A bientot chez nous",
        )
        context = _build_facture_context(self.facture, mode=None, print_settings=print_settings)

        html = render_to_string("joatham_billing/facture_pos_pdf.html", context)

        self.assertIn("A bientot chez nous", html)

    def test_print_settings_view_allows_owner_and_manager_but_blocks_comptable(self):
        manager = create_user("manager-print", "gestionnaire", self.entreprise)
        comptable = create_user("comptable-print", "comptable", self.entreprise)

        owner_response = self.client.get(reverse("print_settings"))
        self.assertEqual(owner_response.status_code, 200)
        self.assertContains(owner_response, "Parametres impression")

        self.client.force_login(manager)
        manager_response = self.client.get(reverse("print_settings"))
        self.assertEqual(manager_response.status_code, 200)

        self.client.force_login(comptable)
        comptable_response = self.client.get(reverse("print_settings"))
        self.assertEqual(comptable_response.status_code, 403)

    def test_print_settings_are_scoped_to_current_entreprise(self):
        other_entreprise = create_entreprise("Entreprise Impression B")
        other_settings = EntreprisePrintSettings.objects.create(
            entreprise=other_entreprise,
            pos_width=EntreprisePrintSettings.POSWidth.WIDTH_80,
            pos_footer_message="Message autre entreprise",
        )

        response = self.client.post(
            reverse("print_settings"),
            {
                "pos_width": EntreprisePrintSettings.POSWidth.WIDTH_58,
                "default_invoice_format": EntreprisePrintSettings.InvoiceFormat.A4,
                "pos_show_logo": "on",
                "pos_show_company_name": "on",
                "pos_show_address": "on",
                "pos_show_phone": "on",
                "pos_show_email": "on",
                "pos_show_tax_info": "on",
                "pos_show_generated_by": "on",
                "pos_footer_message": "Message entreprise A",
            },
        )

        self.assertEqual(response.status_code, 302)
        current_settings = EntreprisePrintSettings.objects.get(entreprise=self.entreprise)
        other_settings.refresh_from_db()
        self.assertEqual(current_settings.pos_width, EntreprisePrintSettings.POSWidth.WIDTH_58)
        self.assertEqual(current_settings.pos_footer_message, "Message entreprise A")
        self.assertEqual(other_settings.pos_width, EntreprisePrintSettings.POSWidth.WIDTH_80)
        self.assertEqual(other_settings.pos_footer_message, "Message autre entreprise")

    def test_add_facture_form_exposes_service_selector_with_price_metadata(self):
        response = self.client.get(reverse("add_facture"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="service_id[]"')
        self.assertContains(response, 'name="product_id[]"')
        self.assertContains(response, 'data-prix="125')
        self.assertContains(response, self.service.nom)
        self.assertContains(response, self.product.nom)
        self.assertContains(response, 'data-stock="3"')

    def test_create_facture_uses_selected_service_when_label_and_price_are_blank(self):
        response = self.client.post(
            reverse("add_facture"),
            {
                "client": self.client_billing.id,
                "client_nom": "",
                "tva": "0",
                "remise": "0",
                "rabais": "0",
                "ristourne": "0",
                "service_id[]": [str(self.service.id)],
                "designation[]": [""],
                "quantite[]": ["2"],
                "prix[]": [""],
            },
        )

        self.assertEqual(response.status_code, 302)
        facture = Facture.objects.exclude(id=self.facture.id).latest("id")
        ligne = facture.lignes.get()
        self.assertEqual(ligne.designation, self.service.nom)
        self.assertEqual(ligne.prix_unitaire, self.service.prix)

    def test_edit_facture_uses_selected_service_and_allows_manual_price_override(self):
        self.facture.statut = Facture.Statut.BROUILLON
        self.facture.paye = False
        self.facture.save(update_fields=["statut", "paye"])

        response = self.client.post(
            reverse("edit_facture", args=[self.facture.id]),
            {
                "client": self.client_billing.id,
                "client_nom": "",
                "tva": "0",
                "remise": "0",
                "rabais": "0",
                "ristourne": "0",
                "service_id[]": [str(self.service.id)],
                "designation[]": [""],
                "quantite[]": ["3"],
                "prix[]": ["150.00"],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.facture.refresh_from_db()
        ligne = self.facture.lignes.get()
        self.assertEqual(ligne.designation, self.service.nom)
        self.assertEqual(ligne.prix_unitaire, Decimal("150.00"))

    def test_create_facture_uses_selected_product_when_manual_fields_are_blank(self):
        response = self.client.post(
            reverse("add_facture"),
            {
                "client": self.client_billing.id,
                "client_nom": "",
                "tva": "16",
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
        facture = Facture.objects.exclude(id=self.facture.id).latest("id")
        ligne = facture.lignes.get()
        self.assertEqual(ligne.produit_id, self.product.id)
        self.assertEqual(ligne.designation, self.product.description)
        self.assertEqual(ligne.prix_unitaire, self.product.prix_unitaire)
        self.assertEqual(ligne.tva, Decimal("16"))

    def test_create_facture_still_supports_manual_line_without_product_or_service(self):
        response = self.client.post(
            reverse("add_facture"),
            {
                "client": self.client_billing.id,
                "client_nom": "",
                "tva": "0",
                "remise": "0",
                "rabais": "0",
                "ristourne": "0",
                "product_id[]": [""],
                "service_id[]": [""],
                "designation[]": ["Ligne libre"],
                "quantite[]": ["1"],
                "prix[]": ["75.00"],
            },
        )

        self.assertEqual(response.status_code, 302)
        facture = Facture.objects.exclude(id=self.facture.id).latest("id")
        ligne = facture.lignes.get()
        self.assertIsNone(ligne.produit_id)
        self.assertEqual(ligne.designation, "Ligne libre")
        self.assertEqual(ligne.prix_unitaire, Decimal("75.00"))

    def test_comptable_sees_read_only_billing_actions_plus_payment(self):
        comptable = create_user("compta-premium", "comptable", self.entreprise)
        self.client.force_login(comptable)

        list_response = self.client.get(reverse("facture_list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, reverse("add_facture"))
        self.assertNotContains(list_response, "Modifier")
        self.assertContains(list_response, "Payer")

        detail_response = self.client.get(reverse("facture_detail", args=[self.facture.id]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertNotContains(detail_response, "Mettre a jour le statut")
        self.assertContains(detail_response, "Enregistrer un paiement")

    def test_billing_module_access_blocks_direct_sensitive_urls(self):
        self.plan.modules_inclus = ["dashboard"]
        self.plan.save(update_fields=["modules_inclus"])
        blocked_urls = [
            reverse("facture_list"),
            reverse("edit_facture", args=[self.facture.id]),
            reverse("change_facture_status", args=[self.facture.id]),
            reverse("add_paiement_facture", args=[self.facture.id]),
            reverse("payer_facture", args=[self.facture.id]),
            reverse("facture_pdf", args=[self.facture.id]),
            reverse("facture_pdf", args=[self.facture.id]) + "?format=pos",
            reverse("print_settings"),
        ]

        for url in blocked_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("module=billing", response["Location"])

    def test_add_paiement_facture_with_caisse_creates_cash_movement(self):
        response = self.client.post(
            reverse("add_paiement_facture", args=[self.facture.id]),
            {
                "montant": "25.00",
                "mode": "especes",
                "reference": "ESP-VIEW",
                "note": "Paiement via vue",
                "caisse": str(self.caisse.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        paiement = self.facture.paiements.latest("id")
        self.assertEqual(paiement.caisse_id, self.caisse.id)
        self.assertEqual(paiement.session_caisse_id, self.session_caisse.id)
        self.assertTrue(
            MouvementCaisse.objects.filter(
                entreprise=self.entreprise,
                source_app="joatham_billing",
                source_model="PaiementFacture",
                source_id=paiement.id,
            ).exists()
        )
