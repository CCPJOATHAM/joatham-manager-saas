import logging
from base64 import b64encode
from decimal import Decimal
from io import BytesIO
from itertools import zip_longest

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _

from core.services.company_profile import build_entreprise_identity, build_logo_data_uri
from core.services.currency import format_amount_for_entreprise, get_currency_code, get_currency_wording
from core.services.product_policy import can_access_module, module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from core.ui_text import FLASH_MESSAGES
from joatham_caisse.selectors.caisse import get_caisses_by_entreprise
from joatham_users.permissions import user_has_permission
from .exceptions import FacturationError
from .models import Facture, FactureHistorique, PaiementFacture, Proforma
from .pdf import PdfRenderError, render_pdf_response
from .permissions import can_manage_factures, can_record_payment, can_view_factures
from .selectors.billing import (
    get_clients_for_billing_by_entreprise,
    get_facture_by_entreprise,
    get_paiements_by_facture_for_entreprise,
    get_factures_by_entreprise,
    get_proforma_by_entreprise,
    get_proformas_by_entreprise,
    get_services_by_entreprise,
)
from joatham_products.selectors.products import get_products_by_entreprise
from .services.facturation import (
    create_facture,
    assert_facture_editable,
    register_payment,
    change_facture_status,
    update_facture,
)
from .services.proforma import (
    assert_proforma_editable,
    cancel_proforma,
    convert_proforma_to_facture,
    create_proforma,
    update_proforma,
)

logger = logging.getLogger(__name__)


def _get_billing_ui_permissions(user):
    return {
        "can_manage_factures_ui": user_has_permission(user, "billing.manage"),
        "can_record_payments_ui": user_has_permission(user, "billing.payments"),
    }


def nombre_en_lettres(n, currency_wording):
    unite = ["", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf"]
    dizaine = ["", "dix", "vingt", "trente", "quarante", "cinquante", "soixante"]

    def convert(nombre):
        if nombre < 10:
            return unite[nombre]
        if nombre < 20:
            return [
                "dix",
                "onze",
                "douze",
                "treize",
                "quatorze",
                "quinze",
                "seize",
                "dix-sept",
                "dix-huit",
                "dix-neuf",
            ][nombre - 10]
        if nombre < 70:
            d, u = divmod(nombre, 10)
            return dizaine[d] + ("-" + unite[u] if u else "")
        if nombre < 100:
            return "soixante-" + convert(nombre - 60)
        if nombre < 1000:
            c, r = divmod(nombre, 100)
            return (unite[c] + " cent" if c > 1 else "cent") + (" " + convert(r) if r else "")
        if nombre < 1000000:
            m, r = divmod(nombre, 1000)
            return convert(m) + " mille" + (" " + convert(r) if r else "")
        return str(nombre)

    texte = convert(int(Decimal(n)))
    return texte.capitalize() + f" {currency_wording}"


def format_tva_percentage(value):
    value = Decimal(value or 0)
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(int(normalized))
    return format(normalized, "f").rstrip("0").rstrip(".")


def _build_legal_information(entreprise):
    identity = build_entreprise_identity(entreprise)
    identity["logo_data_uri"] = build_logo_data_uri(entreprise)
    return identity


def _build_facture_qr_data_uri(facture, legal_information):
    payload = "\n".join(
        [
            f"Entreprise: {legal_information['primary_name']}",
            f"Facture: {facture.numero}",
            f"Date: {facture.date:%d/%m/%Y}",
            f"Client: {facture.client_display}",
            f"Total net: {facture.total_net}",
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


def _build_facture_context(facture, mode):
    lignes = []
    paiements = []
    total_ht = Decimal("0")
    currency_wording = get_currency_wording(get_currency_code(facture.entreprise))

    for index, ligne in enumerate(facture.lignes.all(), start=1):
        total_ligne = Decimal(ligne.quantite) * Decimal(ligne.prix_unitaire)
        total_ht += total_ligne
        lignes.append(
            {
                "index": index,
                "designation": ligne.designation,
                "quantite": ligne.quantite,
                "prix_unitaire": format_amount_for_entreprise(ligne.prix_unitaire, facture.entreprise),
                "total": format_amount_for_entreprise(total_ligne, facture.entreprise),
            }
        )

    total_tva = facture.total_tva
    total_reduction = facture.total_reduction
    total_net = facture.total_net

    generation_time = timezone.localtime(timezone.now())
    invoice_datetime = timezone.localtime(facture.date)
    legal_information = _build_legal_information(facture.entreprise)
    client_name = facture.client_display

    for paiement in facture.paiements.all():
        if paiement.statut != PaiementFacture.StatutPaiement.VALIDE:
            continue
        paiements.append(
            {
                "date_display": timezone.localtime(paiement.date_paiement).strftime("%d/%m/%Y %H:%M"),
                "amount_display": format_amount_for_entreprise(paiement.montant, facture.entreprise),
                "mode_display": paiement.get_mode_display(),
                "reference": paiement.reference,
            }
        )

    line_count = len(lignes)
    compact_layout = mode != "print" and line_count <= 8

    copies = [{"label": _("EXEMPLAIRE CLIENT"), "slug": "client", "compact_layout": compact_layout, "force_page_break": False}]
    if mode != "print":
        copies.append(
            {
                "label": _("EXEMPLAIRE ARCHIVES"),
                "slug": "archives",
                "compact_layout": compact_layout,
                "force_page_break": not compact_layout,
            }
        )

    return {
        "facture": facture,
        "client_name": client_name,
        "invoice_datetime": invoice_datetime.strftime("%d/%m/%Y %H:%M"),
        "tva_display": format_tva_percentage(facture.tva),
        "copies": copies,
        "compact_layout": compact_layout,
        "lignes": lignes,
        "paiements": paiements,
        "latest_payment_mode": paiements[0]["mode_display"] if paiements else _("Non renseigne"),
        "legal_information": legal_information,
        "qr_code_data_uri": _build_facture_qr_data_uri(facture, legal_information),
        "summary": {
            "total_ht": format_amount_for_entreprise(total_ht, facture.entreprise),
            "tva_label": f"TVA ({format_tva_percentage(facture.tva)}%)",
            "total_tva": format_amount_for_entreprise(total_tva, facture.entreprise),
            "has_tva": total_tva > Decimal("0"),
            "remise": format_amount_for_entreprise(total_ht * Decimal(str(facture.remise or 0)) / Decimal('100'), facture.entreprise),
            "rabais": format_amount_for_entreprise(total_ht * Decimal(str(facture.rabais or 0)) / Decimal('100'), facture.entreprise),
            "ristourne": format_amount_for_entreprise(total_ht * Decimal(str(facture.ristourne or 0)) / Decimal('100'), facture.entreprise),
            "total_reduction": format_amount_for_entreprise(total_reduction, facture.entreprise),
            "has_reduction": total_reduction > Decimal("0"),
            "total_net": format_amount_for_entreprise(total_net, facture.entreprise),
            "total_paye": format_amount_for_entreprise(facture.total_paye, facture.entreprise),
            "reste_a_payer": format_amount_for_entreprise(facture.reste_a_payer, facture.entreprise),
            "amount_in_words": nombre_en_lettres(total_net, currency_wording),
        },
        "footer_datetime": generation_time.strftime(f"{legal_information['city']}, le %d/%m/%Y %H:%M:%S"),
    }


def _extract_document_lines_from_post(post_data):
    return [
        {
            "designation": designation,
            "quantite": quantite,
            "prix": prix,
            "service_id": service_id,
            "product_id": product_id,
        }
        for designation, quantite, prix, service_id, product_id in zip_longest(
            post_data.getlist("designation[]"),
            post_data.getlist("quantite[]"),
            post_data.getlist("prix[]"),
            post_data.getlist("service_id[]"),
            post_data.getlist("product_id[]"),
            fillvalue="",
        )
    ]


def _build_proforma_line_rows(proforma, entreprise):
    line_rows = []
    for ligne in proforma.lignes.all():
        if ligne.produit_id:
            line_source = {
                "label": _("Produit"),
                "class": "source-product",
                "name": getattr(ligne.produit, "nom", ""),
            }
        elif ligne.service_id:
            line_source = {
                "label": _("Service"),
                "class": "source-service",
                "name": getattr(ligne.service, "nom", ""),
            }
        else:
            line_source = {
                "label": _("Saisie libre"),
                "class": "source-free",
                "name": "",
            }
        line_rows.append(
            {
                "instance": ligne,
                "source": line_source,
                "unit_price_display": format_amount_for_entreprise(ligne.prix_unitaire, entreprise),
                "total_display": format_amount_for_entreprise(ligne.montant, entreprise),
            }
        )
    return line_rows


def _build_proforma_summary(proforma):
    return {
        "total_ht": format_amount_for_entreprise(proforma.total_ht, proforma.entreprise),
        "tva_label": f"TVA ({format_tva_percentage(proforma.tva)}%)",
        "total_tva": format_amount_for_entreprise(proforma.total_tva, proforma.entreprise),
        "total_reduction": format_amount_for_entreprise(proforma.total_reduction, proforma.entreprise),
        "total_net": format_amount_for_entreprise(proforma.total_net, proforma.entreprise),
    }


def _build_proforma_context(proforma):
    legal_information = _build_legal_information(proforma.entreprise)
    generation_time = timezone.localtime(timezone.now())
    return {
        "proforma": proforma,
        "client_name": proforma.client_display,
        "legal_information": legal_information,
        "lignes": [
            {
                "index": index,
                "designation": ligne.designation,
                "quantite": ligne.quantite,
                "prix_unitaire": format_amount_for_entreprise(ligne.prix_unitaire, proforma.entreprise),
                "total": format_amount_for_entreprise(ligne.montant, proforma.entreprise),
            }
            for index, ligne in enumerate(proforma.lignes.all(), start=1)
        ],
        "summary": _build_proforma_summary(proforma),
        "footer_datetime": generation_time.strftime(f"{legal_information['city']}, le %d/%m/%Y %H:%M:%S"),
    }


def _build_proforma_form_context(*, request, entreprise, proforma=None, page_title, submit_label):
    context = {
        "proforma": proforma,
        "clients": get_clients_for_billing_by_entreprise(entreprise),
        "services": get_services_by_entreprise(entreprise),
        "products": get_products_by_entreprise(entreprise).filter(actif=True),
        "default_tva": getattr(proforma, "tva", None) if proforma else entreprise.taux_tva_defaut,
        "currency_code": get_currency_code(entreprise),
        "page_title": page_title,
        "submit_label": submit_label,
        **_get_billing_ui_permissions(request.user),
    }
    return context


def _aggregate_facture_kpis(factures):
    total_emis = Decimal("0")
    total_encaisse = Decimal("0")
    total_restant = Decimal("0")
    partial_count = 0
    overdue_count = 0
    facture_list = list(factures)

    for facture in facture_list:
        total_emis += facture.total_net
        total_encaisse += facture.total_paye
        total_restant += facture.reste_a_payer
        if facture.est_partiellement_payee:
            partial_count += 1
        if facture.reste_a_payer > 0 and facture.statut != Facture.Statut.ANNULEE:
            overdue_count += 1

    return {
        "facture_count": len(facture_list),
        "total_emis": total_emis,
        "total_encaisse": total_encaisse,
        "total_restant": total_restant,
        "partial_count": partial_count,
        "overdue_count": overdue_count,
        "paid_count": sum(1 for facture in facture_list if facture.statut == Facture.Statut.PAYEE),
    }


@login_required
@module_access_required("billing")
def facture_pdf(request, id):
    can_view_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    facture = get_facture_by_entreprise(entreprise, id)
    mode = request.GET.get("mode")
    invoice_format = (request.GET.get("format") or "a4").lower()
    is_pos_format = invoice_format == "pos"
    context = _build_facture_context(facture, mode)
    disposition = "attachment" if mode == "download" else "inline"
    template_name = "joatham_billing/facture_pos_pdf.html" if is_pos_format else "joatham_billing/facture_pdf.html"
    filename_prefix = "ticket" if is_pos_format else "facture"

    try:
        response = render_pdf_response(
            request,
            template_name,
            context,
            filename=f"{filename_prefix}_{facture.numero}.pdf",
            disposition=disposition,
        )
        facture.log_action(
            action=FactureHistorique.Action.PDF,
            user=request.user,
            description=f"PDF généré en mode {mode or 'inline'}.",
        )
        return response
    except PdfRenderError:
        logger.exception("Erreur generation PDF", extra={"facture_id": facture.id, "entreprise_id": facture.entreprise_id})
        return HttpResponse(_("Erreur lors de la generation du PDF."), status=500)


@login_required
@module_access_required("billing")
def payer_facture(request, id):
    can_record_payment(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    facture = get_facture_by_entreprise(entreprise, id)
    try:
        register_payment(
            facture=facture,
            montant=facture.reste_a_payer,
            mode=PaiementFacture.ModePaiement.ESPECES,
            user=request.user,
            note="Paiement complet via action rapide.",
        )
        messages.success(request, FLASH_MESSAGES["invoice_payment_quick"])
    except FacturationError as exc:
        messages.error(request, str(exc))
    return redirect("facture_detail", id=facture.id)


@login_required
@module_access_required("billing")
def facture_list(request):
    can_view_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    clients = get_clients_for_billing_by_entreprise(entreprise)
    factures = get_factures_by_entreprise(
        entreprise,
        client_id=request.GET.get("client"),
        statut=request.GET.get("statut"),
        search=request.GET.get("search"),
        date_debut=parse_date(request.GET.get("date_debut") or ""),
        date_fin=parse_date(request.GET.get("date_fin") or ""),
    )
    facture_kpis = _aggregate_facture_kpis(factures)

    paginator = Paginator(factures, getattr(settings, "JOATHAM_BILLING_PAGE_SIZE", 20))
    page_obj = paginator.get_page(request.GET.get("page"))
    facture_rows = []
    for facture in page_obj.object_list:
        facture_rows.append(
            {
                "instance": facture,
                "client_name": facture.client_display,
                "date_display": facture.date.strftime("%d/%m/%Y %H:%M"),
                "total_net_display": format_amount_for_entreprise(facture.total_net, entreprise),
                "total_paye_display": format_amount_for_entreprise(facture.total_paye, entreprise),
                "reste_a_payer_display": format_amount_for_entreprise(facture.reste_a_payer, entreprise),
                "is_partial": facture.est_partiellement_payee,
                "can_pay": facture.reste_a_payer > 0 and facture.statut != Facture.Statut.ANNULEE,
            }
        )

    return render(
        request,
        "joatham_billing/facture_list.html",
        {
            "factures": facture_rows,
            "page_obj": page_obj,
            "clients": clients,
            "statut_choices": Facture.Statut.choices,
            "currency_code": get_currency_code(entreprise),
            "facture_count": facture_kpis["facture_count"],
            "total_emis_display": format_amount_for_entreprise(facture_kpis["total_emis"], entreprise),
            "total_encaisse_display": format_amount_for_entreprise(facture_kpis["total_encaisse"], entreprise),
            "total_restant_display": format_amount_for_entreprise(facture_kpis["total_restant"], entreprise),
            "paid_count": facture_kpis["paid_count"],
            "partial_count": facture_kpis["partial_count"],
            "overdue_count": facture_kpis["overdue_count"],
            **_get_billing_ui_permissions(request.user),
        },
    )


@login_required
@module_access_required("billing")
def proforma_list(request):
    can_view_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    proformas = get_proformas_by_entreprise(
        entreprise,
        statut=request.GET.get("statut"),
        search=request.GET.get("search"),
        date_debut=parse_date(request.GET.get("date_debut") or ""),
        date_fin=parse_date(request.GET.get("date_fin") or ""),
    )
    paginator = Paginator(proformas, getattr(settings, "JOATHAM_BILLING_PAGE_SIZE", 20))
    page_obj = paginator.get_page(request.GET.get("page"))
    rows = []
    for proforma in page_obj.object_list:
        rows.append(
            {
                "instance": proforma,
                "client_name": proforma.client_display,
                "date_display": timezone.localtime(proforma.date).strftime("%d/%m/%Y %H:%M"),
                "validity_display": proforma.date_validite.strftime("%d/%m/%Y") if proforma.date_validite else "-",
                "total_net_display": format_amount_for_entreprise(proforma.total_net, entreprise),
                "can_edit": proforma.statut not in {Proforma.Statut.ANNULEE, Proforma.Statut.CONVERTIE},
                "can_convert": proforma.statut not in {Proforma.Statut.ANNULEE, Proforma.Statut.CONVERTIE} and not proforma.facture_convertie_id,
            }
        )

    return render(
        request,
        "joatham_billing/proforma_list.html",
        {
            "proformas": rows,
            "page_obj": page_obj,
            "statut_choices": Proforma.Statut.choices,
            "currency_code": get_currency_code(entreprise),
            **_get_billing_ui_permissions(request.user),
        },
    )


@login_required
@module_access_required("billing")
def add_proforma(request):
    can_manage_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)

    if request.method == "POST":
        try:
            proforma = create_proforma(
                entreprise=entreprise,
                user=request.user,
                client_id=request.POST.get("client") or None,
                client_nom=request.POST.get("client_nom", ""),
                tva=request.POST.get("tva") or 0,
                remise=request.POST.get("remise") or 0,
                rabais=request.POST.get("rabais") or 0,
                ristourne=request.POST.get("ristourne") or 0,
                date_validite=parse_date(request.POST.get("date_validite") or ""),
                notes=request.POST.get("notes", ""),
                conditions=request.POST.get("conditions", ""),
                lignes=_extract_document_lines_from_post(request.POST),
            )
            messages.success(request, _("Proforma creee avec succes."))
            return redirect("proforma_detail", id=proforma.id)
        except FacturationError as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Erreur inattendue creation proforma", extra={"entreprise_id": entreprise.id})
            messages.error(request, _("Une erreur inattendue est survenue lors de la creation de la proforma."))

    return render(
        request,
        "joatham_billing/proforma_form.html",
        _build_proforma_form_context(
            request=request,
            entreprise=entreprise,
            page_title=_("Nouvelle facture proforma"),
            submit_label=_("Creer la proforma"),
        ),
    )


@login_required
@module_access_required("billing")
def edit_proforma(request, id):
    can_manage_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    proforma = get_proforma_by_entreprise(entreprise, id)

    try:
        assert_proforma_editable(proforma)
    except FacturationError as exc:
        messages.error(request, str(exc))
        return redirect("proforma_detail", id=proforma.id)

    if request.method == "POST":
        try:
            update_proforma(
                proforma=proforma,
                user=request.user,
                client_id=request.POST.get("client") or None,
                client_nom=request.POST.get("client_nom", ""),
                tva=request.POST.get("tva") or 0,
                remise=request.POST.get("remise") or 0,
                rabais=request.POST.get("rabais") or 0,
                ristourne=request.POST.get("ristourne") or 0,
                date_validite=parse_date(request.POST.get("date_validite") or ""),
                notes=request.POST.get("notes", ""),
                conditions=request.POST.get("conditions", ""),
                lignes=_extract_document_lines_from_post(request.POST),
            )
            messages.success(request, _("Proforma mise a jour avec succes."))
            return redirect("proforma_detail", id=proforma.id)
        except FacturationError as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Erreur inattendue modification proforma", extra={"proforma_id": proforma.id})
            messages.error(request, _("Une erreur inattendue est survenue lors de la modification de la proforma."))

    return render(
        request,
        "joatham_billing/proforma_form.html",
        _build_proforma_form_context(
            request=request,
            entreprise=entreprise,
            proforma=proforma,
            page_title=_("Modifier la facture proforma"),
            submit_label=_("Enregistrer les modifications"),
        ),
    )


@login_required
@module_access_required("billing")
def proforma_detail(request, id):
    can_view_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    proforma = get_proforma_by_entreprise(entreprise, id)
    line_rows = _build_proforma_line_rows(proforma, entreprise)
    can_manage = user_has_permission(request.user, "billing.manage")
    context = {
        "proforma": proforma,
        "line_rows": line_rows,
        "statut_choices": Proforma.Statut.choices,
        "currency_code": get_currency_code(entreprise),
        "total_ht": format_amount_for_entreprise(proforma.total_ht, entreprise),
        "total_tva": format_amount_for_entreprise(proforma.total_tva, entreprise),
        "total_reduction": format_amount_for_entreprise(proforma.total_reduction, entreprise),
        "total_net": format_amount_for_entreprise(proforma.total_net, entreprise),
        "line_count": len(line_rows),
        "can_edit_proforma": can_manage and proforma.statut not in {Proforma.Statut.ANNULEE, Proforma.Statut.CONVERTIE},
        "can_convert_proforma": can_manage
        and proforma.statut not in {Proforma.Statut.ANNULEE, Proforma.Statut.CONVERTIE}
        and not proforma.facture_convertie_id,
        **_get_billing_ui_permissions(request.user),
    }
    return render(request, "joatham_billing/proforma_detail.html", context)


@login_required
@module_access_required("billing")
def proforma_pdf(request, id):
    can_view_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    proforma = get_proforma_by_entreprise(entreprise, id)
    disposition = "attachment" if request.GET.get("mode") == "download" else "inline"

    try:
        return render_pdf_response(
            request,
            "joatham_billing/proforma_pdf.html",
            _build_proforma_context(proforma),
            filename=f"proforma_{proforma.numero}.pdf",
            disposition=disposition,
        )
    except PdfRenderError:
        logger.exception("Erreur generation PDF proforma", extra={"proforma_id": proforma.id, "entreprise_id": proforma.entreprise_id})
        return HttpResponse(_("Erreur lors de la generation du PDF proforma."), status=500)


@login_required
@module_access_required("billing")
@require_POST
def cancel_proforma_view(request, id):
    can_manage_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    proforma = get_proforma_by_entreprise(entreprise, id)
    try:
        cancel_proforma(proforma=proforma, user=request.user)
        messages.success(request, _("Proforma annulee avec succes."))
    except FacturationError as exc:
        messages.error(request, str(exc))
    return redirect("proforma_detail", id=proforma.id)


@login_required
@module_access_required("billing")
@require_POST
def convert_proforma_view(request, id):
    can_manage_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    proforma = get_proforma_by_entreprise(entreprise, id)
    try:
        facture = convert_proforma_to_facture(proforma=proforma, user=request.user)
        messages.success(request, _("Proforma convertie en facture definitive."))
        return redirect("facture_detail", id=facture.id)
    except FacturationError as exc:
        messages.error(request, str(exc))
    except Exception:
        logger.exception("Erreur inattendue conversion proforma", extra={"proforma_id": proforma.id, "entreprise_id": entreprise.id})
        messages.error(request, _("Une erreur inattendue est survenue lors de la conversion de la proforma."))
    return redirect("proforma_detail", id=proforma.id)


@login_required
@module_access_required("billing")
def add_facture(request):
    can_manage_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    clients = get_clients_for_billing_by_entreprise(entreprise)
    services = get_services_by_entreprise(entreprise)
    products = get_products_by_entreprise(entreprise).filter(actif=True)

    if request.method == "POST":
        lignes = [
            {
                "designation": designation,
                "quantite": quantite,
                "prix": prix,
                "service_id": service_id,
                "product_id": product_id,
            }
            for designation, quantite, prix, service_id, product_id in zip_longest(
                request.POST.getlist("designation[]"),
                request.POST.getlist("quantite[]"),
                request.POST.getlist("prix[]"),
                request.POST.getlist("service_id[]"),
                request.POST.getlist("product_id[]"),
                fillvalue="",
            )
        ]
        try:
            create_facture(
                entreprise=entreprise,
                user=request.user,
                client_id=request.POST.get("client") or None,
                client_nom=request.POST.get("client_nom", ""),
                tva=request.POST.get("tva") or 0,
                remise=request.POST.get("remise") or 0,
                rabais=request.POST.get("rabais") or 0,
                ristourne=request.POST.get("ristourne") or 0,
                lignes=lignes,
            )
            messages.success(request, FLASH_MESSAGES["invoice_created"])
            return redirect("facture_list")
        except FacturationError as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Erreur inattendue creation facture", extra={"entreprise_id": entreprise.id})
            messages.error(request, _("Une erreur inattendue est survenue lors de la creation de la facture."))

    return render(
        request,
        "joatham_billing/add_facture.html",
        {
            "clients": clients,
            "services": services,
            "products": products,
            "default_tva": entreprise.taux_tva_defaut,
            "currency_code": get_currency_code(entreprise),
            **_get_billing_ui_permissions(request.user),
        },
    )


@login_required
@module_access_required("billing")
def edit_facture(request, id):
    can_manage_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    facture = get_facture_by_entreprise(entreprise, id)
    clients = get_clients_for_billing_by_entreprise(entreprise)
    services = get_services_by_entreprise(entreprise)
    products = get_products_by_entreprise(entreprise)

    try:
        assert_facture_editable(facture)
    except FacturationError as exc:
        messages.error(request, str(exc))
        return redirect("facture_detail", id=facture.id)

    if request.method == "POST":
        lignes = [
            {
                "designation": designation,
                "quantite": quantite,
                "prix": prix,
                "service_id": service_id,
                "product_id": product_id,
            }
            for designation, quantite, prix, service_id, product_id in zip_longest(
                request.POST.getlist("designation[]"),
                request.POST.getlist("quantite[]"),
                request.POST.getlist("prix[]"),
                request.POST.getlist("service_id[]"),
                request.POST.getlist("product_id[]"),
                fillvalue="",
            )
        ]
        try:
            update_facture(
                facture=facture,
                user=request.user,
                client_id=request.POST.get("client") or None,
                client_nom=request.POST.get("client_nom", ""),
                tva=request.POST.get("tva") or 0,
                remise=request.POST.get("remise") or 0,
                rabais=request.POST.get("rabais") or 0,
                ristourne=request.POST.get("ristourne") or 0,
                lignes=lignes,
            )
            messages.success(request, FLASH_MESSAGES["invoice_updated"])
            return redirect("facture_detail", id=facture.id)
        except FacturationError as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Erreur inattendue modification facture", extra={"facture_id": facture.id, "entreprise_id": facture.entreprise_id})
            messages.error(request, _("Une erreur inattendue est survenue lors de la modification de la facture."))

    return render(
        request,
        "joatham_billing/edit_facture.html",
        {
            "facture": facture,
            "clients": clients,
            "services": services,
            "products": products,
            "default_tva": entreprise.taux_tva_defaut,
            "currency_code": get_currency_code(entreprise),
            **_get_billing_ui_permissions(request.user),
        },
    )


def test(request):
    return render(request, "test.html")


@login_required
@module_access_required("billing")
def facture_detail(request, id):
    can_view_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    facture = get_facture_by_entreprise(entreprise, id)
    line_rows = []
    for ligne in facture.lignes.all():
        if ligne.produit_id:
            line_source = {
                "label": _("Produit"),
                "class": "source-product",
                "name": getattr(ligne.produit, "nom", ""),
            }
        elif ligne.service_id:
            line_source = {
                "label": _("Service"),
                "class": "source-service",
                "name": getattr(ligne.service, "nom", ""),
            }
        else:
            line_source = {
                "label": _("Saisie libre"),
                "class": "source-free",
                "name": "",
            }
        line_rows.append(
            {
                "instance": ligne,
                "source": line_source,
                "unit_price_display": format_amount_for_entreprise(ligne.prix_unitaire, entreprise),
                "total_display": format_amount_for_entreprise(ligne.montant, entreprise),
            }
        )

    payment_rows = []
    for paiement in get_paiements_by_facture_for_entreprise(entreprise, facture):
        payment_rows.append(
            {
                "instance": paiement,
                "date_display": timezone.localtime(paiement.date_paiement).strftime("%d/%m/%Y %H:%M"),
                "amount_display": format_amount_for_entreprise(paiement.montant, entreprise),
            }
        )

    can_link_cash_payments = can_access_module(request.user, "caisse_integrations")
    context = {
        "facture": facture,
        "line_rows": line_rows,
        "paiements": payment_rows,
        "caisses_actives": get_caisses_by_entreprise(entreprise).filter(est_active=True) if can_link_cash_payments else [],
        "can_link_cash_payments_ui": can_link_cash_payments,
        "historique": facture.historique.all()[:20],
        "statut_choices": Facture.Statut.choices,
        "mode_choices": PaiementFacture.ModePaiement.choices,
        "currency_code": get_currency_code(entreprise),
        "total_ht": format_amount_for_entreprise(facture.total_ht, entreprise),
        "total_tva": format_amount_for_entreprise(facture.total_tva, entreprise),
        "total_net": format_amount_for_entreprise(facture.total_net, entreprise),
        "total_paye": format_amount_for_entreprise(facture.total_paye, entreprise),
        "reste_a_payer": format_amount_for_entreprise(facture.reste_a_payer, entreprise),
        "est_partiellement_payee": facture.est_partiellement_payee,
        "line_count": len(line_rows),
        "payment_count": len(payment_rows),
        **_get_billing_ui_permissions(request.user),
    }
    return render(request, "joatham_billing/facture_detail.html", context)


@login_required
@module_access_required("billing")
def change_facture_status_view(request, id):
    can_manage_factures(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    facture = get_facture_by_entreprise(entreprise, id)
    if request.method == "POST":
        try:
            change_facture_status(
                facture=facture,
                nouveau_statut=request.POST.get("statut"),
                user=request.user,
                note=request.POST.get("note", ""),
            )
            messages.success(request, FLASH_MESSAGES["invoice_status_updated"])
        except FacturationError as exc:
            messages.error(request, str(exc))
    return redirect("facture_detail", id=facture.id)


@login_required
@module_access_required("billing")
def add_paiement_facture(request, id):
    can_record_payment(request.user)
    entreprise = get_user_entreprise_or_raise(request.user)
    facture = get_facture_by_entreprise(entreprise, id)
    if request.method == "POST":
        try:
            register_payment(
                facture=facture,
                montant=request.POST.get("montant") or 0,
                mode=request.POST.get("mode") or PaiementFacture.ModePaiement.ESPECES,
                reference=request.POST.get("reference", ""),
                note=request.POST.get("note", ""),
                caisse=request.POST.get("caisse") or None,
                user=request.user,
            )
            messages.success(request, FLASH_MESSAGES["invoice_payment_created"])
        except FacturationError as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Erreur inattendue paiement facture", extra={"facture_id": facture.id, "entreprise_id": facture.entreprise_id})
            messages.error(request, _("Une erreur inattendue est survenue lors de l'enregistrement du paiement."))
    return redirect("facture_detail", id=facture.id)
