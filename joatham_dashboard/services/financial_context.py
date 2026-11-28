from core.services.currency import format_amount_for_entreprise
from .dashboard_service import build_dashboard_context
from .financial_reporting import executive_financials


def build_executive_context(entreprise, user, period_form):
    context = build_dashboard_context(entreprise, user)
    start = period_form.cleaned_data.get('date_debut')
    end = period_form.cleaned_data.get('date_fin')
    financials = executive_financials(entreprise, start, end)
    amounts = {'total_ca', 'total_encaisse', 'total_depenses', 'benefice', 'total_tva',
               'reste_encaisser', 'gross_receipts', 'refunds'}
    context.update({key: format_amount_for_entreprise(value, entreprise) if key in amounts else value
                    for key, value in financials.items()})
    context.update(period_form=period_form, period_start=start, period_end=end)
    context['labels'] = []
    context['data'] = [financials['payees'], financials['impayees']]
    return context
