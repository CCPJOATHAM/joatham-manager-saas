from datetime import datetime, date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import override

from core.services.subscription import activate_subscription_for_entreprise, get_default_paid_plans
from joatham_billing.models import Facture, LigneFacture, PaiementFacture
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_payments.models import PaymentTransaction
from joatham_users.models import Abonnement
from .services.financial_reporting import executive_financials


def instant(month=1, day=15, hour=12, minute=0, second=0):
    return timezone.make_aware(datetime(2026, month, day, hour, minute, second))


class ExecutiveFinancialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = create_entreprise('Société Àvenir conservée')
        cls.other = create_entreprise('Entreprise privée B')
        cls.owner = create_user('financial-owner', 'proprietaire', cls.company)
        cls.manager = create_user('financial-manager', 'gestionnaire', cls.company)
        plan = Abonnement.objects.create(**next(p for p in get_default_paid_plans() if p['code'] == 'premium'), actif=True)
        activate_subscription_for_entreprise(entreprise=cls.company, plan=plan, utilisateur=cls.owner)

    def invoice(self, amount='100', month=1, company=None, status=Facture.Statut.EMISE):
        invoice = Facture.objects.create(entreprise=company or self.company, montant=Decimal(amount), statut=status)
        LigneFacture.objects.create(facture=invoice, designation='Description française conservée', quantite=1,
                                   prix_unitaire=Decimal(amount))
        Facture.objects.filter(pk=invoice.pk).update(date=instant(month))
        invoice.refresh_from_db()
        return invoice

    def pay(self, invoice, amount, month=1, status='valide', timestamp=None):
        return PaiementFacture.objects.create(facture=invoice, entreprise=invoice.entreprise,
                    montant=Decimal(amount), date_paiement=timestamp or instant(month), statut=status)

    def transaction(self, amount, kind='encaissement', currency='CDF', status='confirme', company=None, **extra):
        return PaymentTransaction.objects.create(entreprise=company or self.company, amount=Decimal(amount),
            transaction_type=kind, currency=currency, status=status, transaction_date=instant(2), **extra)

    def report(self, month=None):
        return executive_financials(self.company, date(2026, month, 1) if month else None,
                                   date(2026, month, 28) if month else None)

    def test_353125_partial_receipts_and_zero_fully_paid_invoices_is_consistent(self):
        invoice = self.invoice('500000')
        self.pay(invoice, '353125')
        for language in ('fr', 'en'):
            with self.subTest(language=language), override(language):
                result = self.report()
                self.assertEqual(result['total_encaisse'], Decimal('353125'))
                self.assertEqual(result['payees'], 0)
                self.assertEqual(result['partial_invoices'], 1)
                self.assertEqual(result['reste_encaisser'], Decimal('146875'))

    def test_historical_boolean_does_not_override_real_balance_or_write_data(self):
        invoice = self.invoice()
        self.pay(invoice, '100')
        Facture.objects.filter(pk=invoice.pk).update(paye=False)
        self.assertEqual(self.report()['payees'], 1)
        invoice.refresh_from_db()
        self.assertFalse(invoice.paye)

    def test_manual_paid_status_without_receipts_is_not_a_settled_invoice(self):
        invoice = self.invoice(status=Facture.Statut.PAYEE)
        Facture.objects.filter(pk=invoice.pk).update(paye=True)
        self.assertEqual(self.report()['payees'], 0)

    def test_invoice_date_and_receipt_date_are_independent(self):
        invoice = self.invoice()
        self.pay(invoice, '100', month=2)
        january, february = self.report(1), self.report(2)
        self.assertEqual((january['total_ca'], january['total_encaisse'], january['payees']), (100, 0, 1))
        self.assertEqual((february['total_ca'], february['total_encaisse'], february['nombre_factures']), (0, 100, 0))

    def test_drafts_and_cancelled_invoices_excluded_but_received_cash_remains(self):
        self.invoice('1000', status=Facture.Statut.BROUILLON)
        cancelled = self.invoice('200', status=Facture.Statut.ANNULEE)
        self.pay(cancelled, '50')
        result = self.report()
        self.assertEqual(result['total_ca'], 0)
        self.assertEqual(result['nombre_factures'], 0)
        self.assertEqual(result['total_encaisse'], 50)

    def test_linked_payments_count_once_refunds_and_currency_are_explicit(self):
        invoice = self.invoice()
        payment = self.pay(invoice, '100', month=2)
        self.transaction('100', facture=invoice, paiement_facture=payment)
        self.transaction('25', currency='FC')
        self.transaction('10', kind='remboursement')
        for status in ('en_attente', 'rejete', 'annule'):
            self.transaction('999', status=status)
        self.transaction('700', currency='USD')
        self.transaction('999', kind='decaissement')
        result = self.report(2)
        self.assertEqual(result['total_encaisse'], 115)
        self.assertEqual(result['gross_receipts'], 125)
        self.assertEqual(result['refunds'], 10)
        self.assertEqual(result['receipt_count'], 2)
        self.assertEqual(result['excluded_currency'], 1)
        self.assertEqual(sum(row['net_receipts'] for row in result['financial_series']), result['total_encaisse'])

    def test_cancelled_invoice_payment_excluded_and_negative_net_receipts_supported(self):
        self.pay(self.invoice(), '25', status='annule')
        self.transaction('40', kind='remboursement')
        result = self.report()
        self.assertEqual(result['total_encaisse'], -40)
        self.assertEqual(result['financial_series'][-1]['net_receipts'], -40)

    def test_period_boundaries_are_local_and_inclusive(self):
        invoice = self.invoice('500')
        self.pay(invoice, '20', timestamp=instant(1, 1, 0))
        self.pay(invoice, '30', timestamp=instant(1, 31, 23, 59, 59))
        self.pay(invoice, '40', timestamp=instant(2, 1, 0))
        result = executive_financials(self.company, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(result['total_encaisse'], 50)

    def test_other_company_and_corrupt_foreign_payment_are_not_aggregated(self):
        invoice = self.invoice('500')
        self.pay(self.invoice('10000', company=self.other), '10000')
        payment = self.pay(invoice, '100')
        PaiementFacture.objects.filter(pk=payment.pk).update(entreprise=self.other)
        self.transaction('999', company=self.other)
        result = self.report()
        self.assertEqual(result['total_ca'], 500)
        self.assertEqual(result['total_encaisse'], 0)
        self.assertEqual(result['partial_invoices'], 0)

    def test_bilingual_view_period_explanations_series_and_company_scope(self):
        invoice = self.invoice('500000')
        self.pay(invoice, '353125')
        for language in ('fr', 'en'):
            self.owner.preferred_language = language
            self.owner.save(update_fields=['preferred_language'])
            self.client.force_login(self.owner)
            response = self.client.get(reverse('admin_dashboard'), {
                'date_debut':'2026-01-01','date_fin':'2026-01-31','entreprise_id':self.other.pk})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['period_start'], date(2026, 1, 1))
            self.assertContains(response, self.company.nom)
            self.assertNotContains(response, self.other.nom)
            self.assertContains(response, '353 125,00 CDF' if language == 'fr' else '353,125.00 CDF')
            self.assertContains(response, 'date du paiement de facture' if language == 'fr' else 'invoice payment date')
            self.assertContains(response, "Chiffre d'affaires facturé" if language == 'fr' else 'Invoiced revenue')
            self.assertContains(response, 'Encaissements validés' if language == 'fr' else 'Validated receipts')
            self.assertContains(response,
                "Total HT des factures enregistrées pendant la période, avant remises, hors brouillons et factures annulées."
                if language == 'fr' else
                "Total excluding tax for invoices recorded during the period, before discounts, excluding drafts and cancelled invoices.")
            self.assertContains(response,
                "La date retenue est la date d'enregistrement de la facture, indépendamment de la date des paiements."
                if language == 'fr' else
                "The invoice creation date determines inclusion, independently of payment dates.")
            self.assertNotContains(response, 'Factures émises ou payées : montant HT avant remises')
            self.assertNotContains(response, 'Issued or paid invoices: amount excluding tax, before discounts')
            self.assertContains(response, 'date de transaction du module Paiements' if language == 'fr' else 'Payments transaction date')
            self.assertContains(response, '<details', count=3)
            self.assertNotContains(response, 'class="kpi-bars"')
            self.assertContains(response, 'financial-series')
        invoice.refresh_from_db()
        self.assertFalse(invoice.paye)

    def test_invalid_dates_show_no_unfiltered_results_and_roles_are_preserved(self):
        self.client.force_login(self.owner)
        for query in ({'date_debut':'2026-02-01','date_fin':'2026-01-01'}, {'date_debut':'not-a-date'}):
            response = self.client.get(reverse('admin_dashboard'), query)
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, 'class="kpi-value"', status_code=400)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('admin_dashboard')).status_code, 403)

    def test_empty_period_has_no_fake_graph_and_default_is_all_history(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['financial_series'], [])
        self.assertIsNone(response.context['period_start'])

    def test_existing_ht_basis_is_retained_and_series_reconciles(self):
        invoice = self.invoice('100')
        invoice.tva = Decimal('16')
        invoice.remise = 10
        invoice.save(update_fields=['tva', 'remise'])
        self.pay(invoice, '106')
        result = self.report()
        self.assertEqual(result['total_ca'], 100)
        self.assertEqual(result['total_tva'], 16)
        self.assertEqual(result['total_encaisse'], 106)
        self.assertEqual(result['payees'], 1)
        self.assertEqual(sum(row['revenue'] for row in result['financial_series']), result['total_ca'])
