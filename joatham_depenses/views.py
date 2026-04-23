from datetime import datetime
from base64 import b64encode
from io import BytesIO

import qrcode
from django.shortcuts import redirect, render

from core.services.company_profile import build_entreprise_identity, build_logo_data_uri
from core.services.currency import format_amount_for_entreprise, format_decimal_number, get_currency_display
from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_billing.pdf import render_pdf_response
from joatham_users.permissions import permission_required, require_permission, user_has_permission

from .forms import DepenseForm
from .services.depenses_service import (
    create_depense_for_entreprise,
    get_depenses_kpis,
    get_depenses_total,
    list_depenses_for_entreprise,
)


def _build_depenses_qr_data_uri(*, entreprise, total, date_generation):
    payload = "\n".join(
        [
            f"Entreprise: {entreprise.nom}",
            "Document: Liste des depenses",
            f"Edition: {date_generation}",
            f"Total: {format_amount_for_entreprise(total, entreprise)}",
            "Genere par JOATHAM Manager",
        ]
    )
    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@permission_required("expenses.view")
@module_access_required("expenses")
def depenses_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = DepenseForm(request.POST or None)

    if request.method == "POST":
        require_permission(request.user, "expenses.manage")
        if form.is_valid():
            create_depense_for_entreprise(form, entreprise, utilisateur=request.user)
            return redirect("depenses")

    date_debut = request.GET.get("date_debut")
    date_fin = request.GET.get("date_fin")
    recherche = request.GET.get("q")
    depenses = list_depenses_for_entreprise(
        entreprise,
        date_debut=date_debut,
        date_fin=date_fin,
        recherche=recherche,
    )
    kpis = get_depenses_kpis(entreprise)
    total = get_depenses_total(depenses)
    depenses_rows = [
        {
            "description": depense.description,
            "amount_display": format_amount_for_entreprise(depense.montant, entreprise),
            "date_display": depense.date.strftime("%d/%m/%Y %H:%M"),
        }
        for depense in depenses
    ]

    return render(
        request,
        "joatham_depenses/depenses.html",
        {
            "form": form,
            "depenses": depenses_rows,
            "total": total,
            "total_display": format_amount_for_entreprise(total, entreprise),
            "depense_count": len(depenses_rows),
            "global_depense_count": kpis["count"],
            "today_total_display": format_amount_for_entreprise(kpis["today_total"], entreprise),
            "month_total_display": format_amount_for_entreprise(kpis["month_total"], entreprise),
            "average_total_display": format_amount_for_entreprise(kpis["average"], entreprise),
            "global_total_display": format_amount_for_entreprise(kpis["total"], entreprise),
            "evolution_display": kpis["evolution_display"],
            "evolution_direction": kpis["evolution_direction"],
            "currency_code": getattr(entreprise, "devise", "CDF"),
            "date_debut": date_debut or "",
            "date_fin": date_fin or "",
            "search": recherche or "",
            "can_manage_expenses_ui": user_has_permission(request.user, "expenses.manage"),
        },
    )


@permission_required("expenses.export")
def depenses_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    date_debut = request.GET.get("date_debut")
    date_fin = request.GET.get("date_fin")
    recherche = request.GET.get("q")
    depenses = list_depenses_for_entreprise(
        entreprise,
        date_debut=date_debut,
        date_fin=date_fin,
        recherche=recherche,
    )
    total = get_depenses_total(depenses)
    date_generation = datetime.now().strftime("%d/%m/%Y")
    entreprise_identity = build_entreprise_identity(entreprise)
    entreprise_identity["logo_data_uri"] = build_logo_data_uri(entreprise)
    if date_debut and date_fin:
        period_label = f"Periode du {date_debut} au {date_fin}"
    elif date_debut:
        period_label = f"Periode a partir du {date_debut}"
    elif date_fin:
        period_label = f"Periode jusqu'au {date_fin}"
    else:
        period_label = "Toutes les depenses enregistrees"

    depenses_rows = [
        {
            "date": depense.date.strftime("%d/%m/%Y"),
            "description": depense.description,
            "amount": format_decimal_number(depense.montant),
        }
        for depense in depenses
    ]

    return render_pdf_response(
        request,
        "joatham_depenses/pdf_depenses.html",
        {
            "depenses": depenses_rows,
            "total": total,
            "total_display": format_amount_for_entreprise(total, entreprise),
            "entreprise": entreprise,
            "currency_code": getattr(entreprise, "devise", "CDF"),
            "currency_display": get_currency_display(getattr(entreprise, "devise", "CDF")),
            "entreprise_identity": entreprise_identity,
            "date_generation": date_generation,
            "date_footer": datetime.now().strftime("%d/%m/%Y a %H:%M:%S"),
            "period_label": period_label,
            "depense_count": len(depenses_rows),
            "qr_code_data_uri": _build_depenses_qr_data_uri(
                entreprise=entreprise,
                total=total,
                date_generation=date_generation,
            ),
        },
        filename="depenses.pdf",
        disposition="attachment",
    )
