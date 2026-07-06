from base64 import b64encode
from decimal import Decimal, InvalidOperation
from io import BytesIO

import qrcode
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from core.selectors.audit import get_inscription_billing_history
from core.services.company_profile import build_logo_data_uri
from core.services.currency import format_amount_for_entreprise
from core.services.product_policy import module_access_required
from core.services.quotas import PlanQuotaExceeded
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_billing.pdf import render_pdf_response
from joatham_billing.exceptions import FacturationError
from joatham_billing.selectors.billing import get_factures_by_entreprise
from joatham_users.permissions import permission_required, user_has_permission

from .models import InscriptionFormation, PaiementInscription
from .selectors.apprenants import (
    enrich_paiements_with_document_data,
    get_apprenants_by_entreprise,
    get_filtered_inscriptions_by_entreprise,
    get_formation_by_entreprise,
    get_formations_by_entreprise,
    get_inscription_by_entreprise,
    get_inscriptions_by_entreprise,
    get_paiement_by_inscription,
    get_paiement_document_data,
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
from .services.billing_integration import (
    generate_facture_for_inscription,
    link_facture_to_inscription,
    unlink_facture_from_inscription,
)
from .services.export_service import build_report_metadata, build_xlsx_response


PAYMENT_DOCUMENT_COPY_LABELS = ("Copie apprenant(e)", "Copie archive entreprise")


def _get_apprenants_ui_permissions(user):
    return {
        "can_manage_apprenants_ui": user_has_permission(user, "apprenants.manage"),
        "can_add_apprenants_ui": user_has_permission(user, "apprenants.add"),
        "can_record_apprenant_payments_ui": user_has_permission(user, "apprenants.payments"),
        "can_manage_inscription_billing_ui": user_has_permission(user, "apprenants.manage")
        and user_has_permission(user, "billing.manage"),
    }


def _build_paiement_document_qr(request, entreprise, inscription, paiement, document):
    document_url = request.build_absolute_uri()
    payload = "\n".join(
        [
            f"Document: {document['document_title']}",
            f"URL: {document_url}",
            f"Entreprise: {entreprise.nom}",
            f"Apprenant: {inscription.apprenant}",
            f"Formation: {inscription.formation}",
            f"Paiement: {paiement.id}",
            f"Reference: {paiement.reference or '-'}",
            f"Montant operation: {paiement.montant}",
            f"Date paiement: {paiement.date_paiement:%d/%m/%Y}",
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
    return {
        "qr_code_data_uri": f"data:image/png;base64,{encoded}",
        "qr_code_payload": payload,
    }


def _build_paiement_document_amounts(entreprise, inscription, paiement, document):
    return {
        "montant_prevu": format_amount_for_entreprise(inscription.montant_prevu, entreprise),
        "montant_operation": format_amount_for_entreprise(paiement.montant, entreprise),
        "montant_paye_cumule": format_amount_for_entreprise(document["montant_paye_cumule"], entreprise),
        "solde_restant": format_amount_for_entreprise(document["solde_restant"], entreprise),
        "trop_percu": format_amount_for_entreprise(document["trop_percu"], entreprise),
    }


@permission_required("apprenants.view")
@module_access_required("apprenants")
def apprenants_dashboard(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    formation_id = request.GET.get("formation", "").strip()
    statut = request.GET.get("statut", "").strip()
    dashboard_data = get_apprenants_dashboard_data(
        entreprise,
        formation_id=formation_id or None,
        statut=statut or None,
    )
    context = {
        "entreprise": entreprise,
        **dashboard_data,
        **_get_apprenants_ui_permissions(request.user),
    }
    return render(request, "joatham_apprenants/dashboard.html", context)


@permission_required("apprenants.view")
@module_access_required("apprenants")
def apprenant_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    apprenants = get_apprenants_by_entreprise(entreprise)
    inscriptions = get_inscriptions_by_entreprise(entreprise)
    return render(
        request,
        "joatham_apprenants/apprenant_list.html",
        {
            "apprenants": apprenants,
            "inscriptions": inscriptions,
            "entreprise": entreprise,
            **_get_apprenants_ui_permissions(request.user),
        },
    )


@permission_required("apprenants.add")
@module_access_required("apprenants")
def apprenant_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    context = {"entreprise": entreprise, **_get_apprenants_ui_permissions(request.user)}

    if request.method == "POST":
        actif = request.POST.get("actif") == "on"
        try:
            create_apprenant(
                entreprise=entreprise,
                nom=request.POST.get("nom", ""),
                prenom=request.POST.get("prenom", ""),
                telephone=request.POST.get("telephone", ""),
                email=request.POST.get("email", ""),
                adresse=request.POST.get("adresse", ""),
                observations=request.POST.get("observations", ""),
                actif=actif,
                utilisateur=request.user,
            )
        except (ValidationError, PlanQuotaExceeded) as exc:
            context["error"] = str(exc)
            return render(request, "joatham_apprenants/apprenant_form.html", context, status=400)
        return redirect("apprenant_list")

    return render(request, "joatham_apprenants/apprenant_form.html", context)


@permission_required("apprenants.view")
@module_access_required("apprenants")
def formation_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    formations = get_formations_by_entreprise(entreprise)
    return render(
        request,
        "joatham_apprenants/formation_list.html",
        {"formations": formations, "entreprise": entreprise, **_get_apprenants_ui_permissions(request.user)},
    )


@permission_required("apprenants.manage")
@module_access_required("apprenants")
def formation_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    context = {"entreprise": entreprise, "formation": None, **_get_apprenants_ui_permissions(request.user)}

    if request.method == "POST":
        try:
            prix = Decimal(request.POST.get("prix", "0") or "0")
        except InvalidOperation:
            context["error"] = _("Le prix saisi est invalide.")
            return render(request, "joatham_apprenants/formation_form.html", context, status=400)

        create_formation(
            entreprise=entreprise,
            nom=request.POST.get("nom", ""),
            description=request.POST.get("description", ""),
            prix=prix,
            duree=request.POST.get("duree", ""),
            actif=request.POST.get("actif") == "on",
            utilisateur=request.user,
        )
        return redirect("formation_list")

    return render(request, "joatham_apprenants/formation_form.html", context)


@permission_required("apprenants.manage")
@module_access_required("apprenants")
def formation_update(request, formation_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    formation = get_formation_by_entreprise(entreprise, formation_id)
    context = {"entreprise": entreprise, "formation": formation, **_get_apprenants_ui_permissions(request.user)}

    if request.method == "POST":
        try:
            prix = Decimal(request.POST.get("prix", "0") or "0")
        except InvalidOperation:
            context["error"] = _("Le prix saisi est invalide.")
            return render(request, "joatham_apprenants/formation_form.html", context, status=400)

        update_formation(
            formation,
            nom=request.POST.get("nom", ""),
            description=request.POST.get("description", ""),
            prix=prix,
            duree=request.POST.get("duree", ""),
            actif=request.POST.get("actif") == "on",
            utilisateur=request.user,
        )
        return redirect("formation_list")

    return render(request, "joatham_apprenants/formation_form.html", context)


@permission_required("apprenants.manage")
@module_access_required("apprenants")
def formation_toggle_status(request, formation_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    formation = get_formation_by_entreprise(entreprise, formation_id)
    if request.method == "POST":
        toggle_formation_active(
            formation,
            actif=not formation.actif,
            utilisateur=request.user,
        )
    return redirect("formation_list")


@permission_required("apprenants.manage")
@module_access_required("apprenants")
def inscription_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    apprenants = get_apprenants_by_entreprise(entreprise).filter(actif=True)
    formations = get_formations_by_entreprise(entreprise).filter(actif=True)
    context = {
        "apprenants": apprenants,
        "formations": formations,
        "statuts": InscriptionFormation.Statut.choices,
        "entreprise": entreprise,
        **_get_apprenants_ui_permissions(request.user),
    }

    if request.method == "POST":
        montant_prevu_raw = request.POST.get("montant_prevu", "")
        try:
            montant_prevu = Decimal(montant_prevu_raw) if montant_prevu_raw else None
        except InvalidOperation:
            context["error"] = _("Le montant prévu saisi est invalide.")
            return render(request, "joatham_apprenants/inscription_form.html", context, status=400)

        try:
            inscrire_apprenant_a_formation(
                entreprise=entreprise,
                apprenant_id=request.POST.get("apprenant"),
                formation_id=request.POST.get("formation"),
                statut=request.POST.get("statut") or InscriptionFormation.Statut.EN_COURS,
                montant_prevu=montant_prevu,
                utilisateur=request.user,
            )
        except ValidationError as exc:
            context["error"] = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return render(request, "joatham_apprenants/inscription_form.html", context, status=400)
        return redirect("apprenant_list")

    return render(request, "joatham_apprenants/inscription_form.html", context)


@permission_required("apprenants.view")
@module_access_required("apprenants")
def inscription_detail(request, inscription_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)
    paiements = enrich_paiements_with_document_data(
        inscription,
        get_paiements_by_inscription(entreprise, inscription),
    )
    billing_history = get_inscription_billing_history(inscription)
    factures_candidates = (
        get_factures_by_entreprise(entreprise)
        .filter(inscriptions_formations__isnull=True)
        .order_by("-date")[:20]
    )
    facture_link_mode = ""
    facture_link_event = next(
        (
            entry["log"]
            for entry in billing_history
            if entry["action"] in {"facture_inscription_creee", "facture_existante_liee_inscription"}
        ),
        None,
    )
    if facture_link_event:
        facture_link_mode = {
            "facture_inscription_creee": "cree_depuis_inscription",
            "facture_existante_liee_inscription": "liee_manuellement",
        }.get(facture_link_event.action, "")
    return render(
        request,
        "joatham_apprenants/inscription_detail.html",
        {
            "entreprise": entreprise,
            "inscription": inscription,
            "paiements": paiements,
            "billing_history": billing_history,
            "factures_candidates": factures_candidates,
            "facture_link_mode": facture_link_mode,
            **_get_apprenants_ui_permissions(request.user),
        },
    )


@permission_required("apprenants.manage")
@module_access_required("apprenants")
def inscription_update_montant_prevu(request, inscription_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)

    if request.method == "POST":
        try:
            update_inscription_montant_prevu(
                entreprise=entreprise,
                inscription_id=inscription.id,
                montant_prevu=request.POST.get("montant_prevu", ""),
                utilisateur=request.user,
            )
            messages.success(request, _("Le montant prévu de la formation a été mis à jour."))
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, "messages") else str(exc))

    return redirect("inscription_detail", inscription_id=inscription.id)


@permission_required("apprenants.payments")
@module_access_required("apprenants")
def paiement_inscription_create(request, inscription_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)
    paiements = enrich_paiements_with_document_data(
        inscription,
        get_paiements_by_inscription(entreprise, inscription),
    )
    context = {
        "entreprise": entreprise,
        "inscription": inscription,
        "paiements": paiements,
        "modes_paiement": PaiementInscription.ModePaiement.choices,
        **_get_apprenants_ui_permissions(request.user),
    }

    if request.method == "POST":
        try:
            montant = Decimal(request.POST.get("montant", "0") or "0")
        except InvalidOperation:
            context["error"] = _("Le montant saisi est invalide.")
            return render(request, "joatham_apprenants/paiement_form.html", context, status=400)

        try:
            create_paiement_inscription(
                entreprise=entreprise,
                inscription_id=inscription.id,
                montant=montant,
                mode_paiement=request.POST.get("mode_paiement"),
                reference=request.POST.get("reference", ""),
                observations=request.POST.get("observations", ""),
                utilisateur=request.user,
            )
        except ValidationError as exc:
            context["error"] = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return render(request, "joatham_apprenants/paiement_form.html", context, status=400)
        return redirect("inscription_detail", inscription_id=inscription.id)

    return render(request, "joatham_apprenants/paiement_form.html", context)


@permission_required("apprenants.view")
@module_access_required("apprenants")
def paiement_inscription_document_pdf(request, inscription_id, paiement_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)
    paiement = get_paiement_by_inscription(entreprise, inscription, paiement_id)
    document = get_paiement_document_data(inscription, paiement)
    if document is None:
        raise Http404("Document de paiement introuvable.")

    context = {
        "inscription": inscription,
        "paiement": paiement,
        "document": document,
        "document_copies": PAYMENT_DOCUMENT_COPY_LABELS,
        "document_amounts": _build_paiement_document_amounts(entreprise, inscription, paiement, document),
        "logo_data_uri": build_logo_data_uri(entreprise),
        **_build_paiement_document_qr(request, entreprise, inscription, paiement, document),
        **build_report_metadata(entreprise=entreprise, title=_(document["document_title"])),
    }
    return render_pdf_response(
        request,
        "joatham_apprenants/paiement_inscription_document_pdf.html",
        context,
        filename=f"inscription-{inscription.id}-paiement-{paiement.id}-{document['document_type']}.pdf",
        disposition="attachment",
    )

@permission_required("apprenants.manage")
@module_access_required("apprenants")
def inscription_generate_facture(request, inscription_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)

    if request.method == "POST":
        try:
            facture = generate_facture_for_inscription(
                entreprise=entreprise,
                inscription_id=inscription.id,
                utilisateur=request.user,
            )
            messages.success(request, _("La facture %(numero)s a ete creee et liee a l'inscription.") % {"numero": facture.numero})
        except (ValidationError, FacturationError) as exc:
            messages.error(request, str(exc))

    return redirect("inscription_detail", inscription_id=inscription.id)


@permission_required("apprenants.manage")
@module_access_required("apprenants")
def inscription_link_existing_facture(request, inscription_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)

    if request.method == "POST":
        try:
            facture = link_facture_to_inscription(
                entreprise=entreprise,
                inscription_id=inscription.id,
                facture_id=request.POST.get("facture_id"),
                utilisateur=request.user,
            )
            messages.success(request, _("La facture %(numero)s a ete liee a l'inscription.") % {"numero": facture.numero})
        except (ValidationError, FacturationError) as exc:
            messages.error(request, str(exc))

    return redirect("inscription_detail", inscription_id=inscription.id)


@permission_required("apprenants.manage")
@module_access_required("apprenants")
def inscription_unlink_facture(request, inscription_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)

    if request.method == "POST":
        try:
            facture = unlink_facture_from_inscription(
                entreprise=entreprise,
                inscription_id=inscription.id,
                facture_id=request.POST.get("facture_id") or inscription.facture_id,
                utilisateur=request.user,
            )
            messages.success(request, _("La facture %(numero)s a ete deliee de l'inscription.") % {"numero": facture.numero})
        except (ValidationError, FacturationError) as exc:
            messages.error(request, str(exc))

    return redirect("inscription_detail", inscription_id=inscription.id)


@permission_required("apprenants.view")
@module_access_required("apprenants")
def apprenants_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    apprenants = get_apprenants_by_entreprise(entreprise)
    context = {
        "apprenants": apprenants,
        **build_report_metadata(entreprise=entreprise, title=_("Liste des apprenants")),
    }
    return render_pdf_response(
        request,
        "joatham_apprenants/apprenants_pdf.html",
        context,
        filename="apprenants.pdf",
        disposition="attachment",
    )


@permission_required("apprenants.view")
@module_access_required("apprenants")
def apprenants_excel(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    apprenants = get_apprenants_by_entreprise(entreprise)
    rows = [
        [
            apprenant.nom,
            apprenant.prenom,
            apprenant.telephone,
            apprenant.email,
            apprenant.date_inscription.strftime("%d/%m/%Y"),
            _("Oui") if apprenant.actif else _("Non"),
        ]
        for apprenant in apprenants
    ]
    return build_xlsx_response(
        filename="apprenants.xlsx",
        sheet_name="Apprenants",
        headers=[_("Nom"), _("Prenom"), _("Telephone"), _("Email"), _("Date inscription"), _("Actif")],
        rows=rows,
    )


@permission_required("apprenants.view")
@module_access_required("apprenants")
def formations_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    formations = get_formations_by_entreprise(entreprise)
    context = {
        "formations": formations,
        **build_report_metadata(entreprise=entreprise, title=_("Liste des formations")),
    }
    return render_pdf_response(
        request,
        "joatham_apprenants/formations_pdf.html",
        context,
        filename="formations.pdf",
        disposition="attachment",
    )


@permission_required("apprenants.view")
@module_access_required("apprenants")
def formations_excel(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    formations = get_formations_by_entreprise(entreprise)
    rows = [
        [formation.nom, formation.description, formation.prix, formation.duree, _("Oui") if formation.actif else _("Non")]
        for formation in formations
    ]
    return build_xlsx_response(
        filename="formations.xlsx",
        sheet_name="Formations",
        headers=[_("Nom"), _("Description"), _("Prix"), _("Duree"), _("Actif")],
        rows=rows,
    )


def _get_inscriptions_export_queryset(request, entreprise):
    return get_filtered_inscriptions_by_entreprise(
        entreprise,
        formation_id=request.GET.get("formation", "").strip() or None,
        statut=request.GET.get("statut", "").strip() or None,
        apprenant_id=request.GET.get("apprenant", "").strip() or None,
    )


@permission_required("apprenants.view")
@module_access_required("apprenants")
def inscriptions_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscriptions = _get_inscriptions_export_queryset(request, entreprise)
    context = {
        "inscriptions": inscriptions,
        **build_report_metadata(entreprise=entreprise, title=_("Liste des inscriptions")),
    }
    return render_pdf_response(
        request,
        "joatham_apprenants/inscriptions_pdf.html",
        context,
        filename="inscriptions.pdf",
        disposition="attachment",
    )


@permission_required("apprenants.view")
@module_access_required("apprenants")
def inscriptions_excel(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscriptions = _get_inscriptions_export_queryset(request, entreprise)
    rows = [
        [
            str(inscription.apprenant),
            str(inscription.formation),
            inscription.date_inscription.strftime("%d/%m/%Y"),
            inscription.get_statut_display(),
            inscription.montant_prevu,
            inscription.montant_paye,
            inscription.solde,
            inscription.statut_paiement_label,
            inscription.trop_percu,
        ]
        for inscription in inscriptions
    ]
    return build_xlsx_response(
        filename="inscriptions.xlsx",
        sheet_name="Inscriptions",
        headers=[
            _("Apprenant"),
            _("Formation"),
            _("Date inscription"),
            _("Statut"),
            _("Montant prévu"),
            _("Montant payé"),
            _("Solde"),
            _("Statut de paiement"),
            _("Trop-perçu"),
        ],
        rows=rows,
    )


@permission_required("apprenants.view")
@module_access_required("apprenants")
def inscription_paiements_pdf(request, inscription_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)
    paiements = get_paiements_by_inscription(entreprise, inscription)
    context = {
        "inscription": inscription,
        "paiements": paiements,
        **build_report_metadata(entreprise=entreprise, title=_("Historique des paiements")),
    }
    return render_pdf_response(
        request,
        "joatham_apprenants/paiements_inscription_pdf.html",
        context,
        filename=f"inscription-{inscription.id}-paiements.pdf",
        disposition="attachment",
    )


@permission_required("apprenants.view")
@module_access_required("apprenants")
def inscription_paiements_excel(request, inscription_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)
    paiements = get_paiements_by_inscription(entreprise, inscription)
    rows = [
        [
            paiement.date_paiement.strftime("%d/%m/%Y"),
            paiement.montant,
            paiement.get_mode_paiement_display(),
            paiement.reference,
            str(paiement.utilisateur or ""),
            paiement.observations,
        ]
        for paiement in paiements
    ]
    return build_xlsx_response(
        filename=f"inscription-{inscription.id}-paiements.xlsx",
        sheet_name="Paiements",
        headers=[_("Date paiement"), _("Montant"), _("Mode"), _("Reference"), _("Utilisateur"), _("Observations")],
        rows=rows,
    )


@permission_required("apprenants.view")
@module_access_required("apprenants")
def apprenants_dashboard_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    formation_id = request.GET.get("formation", "").strip()
    statut = request.GET.get("statut", "").strip()
    dashboard_data = get_apprenants_dashboard_data(
        entreprise,
        formation_id=formation_id or None,
        statut=statut or None,
    )
    context = {
        **dashboard_data,
        **build_report_metadata(entreprise=entreprise, title=_("Synthese dashboard apprenants")),
    }
    return render_pdf_response(
        request,
        "joatham_apprenants/dashboard_pdf.html",
        context,
        filename="dashboard-apprenants.pdf",
        disposition="attachment",
    )


@permission_required("apprenants.view")
@module_access_required("apprenants")
def apprenants_dashboard_excel(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    formation_id = request.GET.get("formation", "").strip()
    statut = request.GET.get("statut", "").strip()
    dashboard_data = get_apprenants_dashboard_data(
        entreprise,
        formation_id=formation_id or None,
        statut=statut or None,
    )
    kpis = dashboard_data["kpis"]
    rows = [
        ["Apprenants actifs", kpis["active_apprenants"]],
        ["Formations actives", kpis["active_formations"]],
        ["Total inscriptions", kpis["total_inscriptions"]],
        ["Inscriptions non soldees", kpis["overdue_inscriptions"]],
        ["Total du", kpis["total_du"]],
        ["Total paye", kpis["total_paye"]],
        ["Total restant", kpis["total_restant"]],
    ]
    return build_xlsx_response(
        filename="dashboard-apprenants.xlsx",
        sheet_name="Dashboard",
        headers=[_("Indicateur"), _("Valeur")],
        rows=rows,
    )
