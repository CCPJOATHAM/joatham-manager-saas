"""Read-only executive reporting. Never synchronizes persisted invoice states."""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Prefetch, Q
from django.utils import timezone

from core.services.currency import get_currency_code, format_amount_for_entreprise
from core.services.tenancy import scope_queryset_to_entreprise
from core.services.world import normalize_currency_code
from joatham_billing.models import Facture, PaiementFacture
from joatham_billing.selectors.billing import get_factures_by_entreprise
from joatham_depenses.models import Depense
from joatham_payments.models import PaymentTransaction


ZERO = Decimal('0')


def in_period(queryset, field, start, end):
    if start:
        queryset = queryset.filter(**{field + '__date__gte': start})
    if end:
        queryset = queryset.filter(**{field + '__date__lte': end})
    return queryset


def executive_financials(entreprise, start=None, end=None):
    currency = get_currency_code(entreprise)
    # The invoice amount is the existing stored HT basis, before discounts.
    invoices = list(in_period(get_factures_by_entreprise(entreprise), 'date', start, end).filter(
        statut__in=[Facture.Statut.EMISE, Facture.Statut.PAYEE]).prefetch_related(None).prefetch_related(
            'lignes', Prefetch('paiements', queryset=PaiementFacture.objects.filter(entreprise=entreprise))))
    payments = in_period(scope_queryset_to_entreprise(PaiementFacture.objects.all(), entreprise),
                         'date_paiement', start, end).filter(
        facture__entreprise=entreprise, statut=PaiementFacture.StatutPaiement.VALIDE)
    # A linked transaction is a second representation of the same receipt.
    transactions = in_period(scope_queryset_to_entreprise(PaymentTransaction.objects.all(), entreprise),
                             'transaction_date', start, end).filter(
        status=PaymentTransaction.Status.CONFIRME,
        transaction_type__in=[PaymentTransaction.TransactionType.ENCAISSEMENT,
                              PaymentTransaction.TransactionType.REMBOURSEMENT],
        paiement_facture__isnull=True).filter(Q(facture__isnull=True) | Q(facture__entreprise=entreprise))
    monthly = defaultdict(lambda: {'revenue': ZERO, 'receipts': ZERO, 'refunds': ZERO})
    def month(value):
        return timezone.localtime(value).date().replace(day=1)
    total_ca = ZERO
    total_tva = ZERO
    remaining = ZERO
    paid = partial = 0
    for invoice in invoices:
        total_ca += invoice.montant
        total_tva += invoice.montant * invoice.tva / Decimal('100')
        remaining += invoice.reste_a_payer
        paid += invoice.total_paye > ZERO and invoice.reste_a_payer == ZERO
        partial += invoice.est_partiellement_payee
        monthly[month(invoice.date)]['revenue'] += invoice.montant
    receipts = refunds = ZERO
    receipt_count = excluded_currency = 0
    for payment in payments:
        receipts += payment.montant
        receipt_count += 1
        monthly[month(payment.date_paiement)]['receipts'] += payment.montant
    for payment in transactions:
        if normalize_currency_code(payment.currency) != currency:
            excluded_currency += 1
            continue
        if payment.transaction_type == PaymentTransaction.TransactionType.REMBOURSEMENT:
            refunds += payment.amount
            monthly[month(payment.transaction_date)]['refunds'] += payment.amount
        else:
            receipts += payment.amount
            receipt_count += 1
            monthly[month(payment.transaction_date)]['receipts'] += payment.amount
    expenses = in_period(scope_queryset_to_entreprise(Depense.objects.all(), entreprise), 'date', start, end)
    total_expenses = sum(expenses.values_list('montant', flat=True), ZERO)
    series = [{'month': key, **value, 'net_receipts': value['receipts'] - value['refunds']}
              for key, value in sorted(monthly.items())]
    maximum = max([abs(row[field]) for row in series for field in ('revenue', 'net_receipts')] + [Decimal('1')])
    for row in series:
        row['revenue_width'] = int(abs(row['revenue']) / maximum * 100)
        row['receipts_width'] = int(abs(row['net_receipts']) / maximum * 100)
        row['revenue_display'] = format_amount_for_entreprise(row['revenue'], entreprise)
        row['receipts_display'] = format_amount_for_entreprise(row['net_receipts'], entreprise)
    return {
        'total_ca': total_ca, 'total_encaisse': receipts - refunds, 'gross_receipts': receipts,
        'refunds': refunds, 'receipt_count': receipt_count, 'excluded_currency': excluded_currency,
        'total_depenses': total_expenses, 'benefice': total_ca - total_expenses, 'total_tva': total_tva,
        'reste_encaisser': remaining, 'payees': paid, 'impayees': len(invoices) - paid,
        'partial_invoices': partial, 'nombre_factures': len(invoices), 'financial_series': series,
    }
