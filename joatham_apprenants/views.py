from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from core.selectors.audit import get_inscription_billing_history
from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_billing.pdf import render_pdf_response
from joatham_billing.exceptions import FacturationError
from joatham_billing.selectors.billing import get_factures_by_entreprise
from joatham_users.permissions import permission_required, user_has_permission

from .models import InscriptionFormation, PaiementInscription
from .selectors.apprenants import (
    get_apprenants_by_entreprise,
    get_filtered_inscriptions_by_entreprise,
    get_formation_by_entreprise,
    get_formations_by_entreprise,
    get_inscription_by_entreprise,
    get_inscriptions_by_entreprise,
    get_paiements_by_inscription,
)
from .selectors.dashboard import get_apprenants_dashboard_data
from .services.apprenants_service import (
    create_apprenant,
    create_formation,
    create_paiement_inscription,
    inscrire_apprenant_a_formation,
    toggle_formation_active,
    update_formation,
)
from .services.billing_integration import (
    generate_facture_for_inscription,
    link_facture_to_inscription,
    unlink_facture_from_inscription,
)
from .services.export_service import build_report_metadata, build_xlsx_response


def _get_apprenants_ui_permissions(user):
    return {
        "can_manage_apprenants_ui": user_has_permission(user, "apprenants.manage"),
        "can_add_apprenants_ui": user_has_permission(user, "apprenants.add"),
        "can_record_apprenant_payments_ui": user_has_permission(user, "apprenants.payments"),
        "can_manage_inscription_billing_ui": user_has_permission(user, "apprenants.manage")
        and user_has_permission(user, "billing.manage"),
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
    context = {"entreprise": entreprise}

    if request.method == "POST":
        actif = request.POST.get("actif") == "on"
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
        return redirect("apprenant_list")

    return render(request, "joatham_apprenants/apprenant_form.html", context)


@permission_required("apprenants.view")
def formation_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    formations = get_formations_by_entreprise(entreprise)
    return render(
        request,
        "joatham_apprenants/formation_list.html",
        {"formations": formations, "entreprise": entreprise, **_get_apprenants_ui_permissions(request.user)},
    )


@permission_required("apprenants.manage")
def formation_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    context = {"entreprise": entreprise, "formation": None}

    if request.method == "POST":
        try:
            prix = Decimal(request.POST.get("prix", "0") or "0")
        except InvalidOperation:
            context["error"] = "Le prix saisi est invalide."
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
def formation_update(request, formation_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    formation = get_formation_by_entreprise(entreprise, formation_id)
    context = {"entreprise": entreprise, "formation": formation}

    if request.method == "POST":
        try:
            prix = Decimal(request.POST.get("prix", "0") or "0")
        except InvalidOperation:
            context["error"] = "Le prix saisi est invalide."
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
def inscription_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    apprenants = get_apprenants_by_entreprise(entreprise).filter(actif=True)
    formations = get_formations_by_entreprise(entreprise).filter(actif=True)
    context = {
        "apprenants": apprenants,
        "formations": formations,
        "statuts": InscriptionFormation.Statut.choices,
        "entreprise": entreprise,
    }

    if request.method == "POST":
        montant_prevu_raw = request.POST.get("montant_prevu", "")
        montant_paye_raw = request.POST.get("montant_paye", "")
        try:
            montant_prevu = Decimal(montant_prevu_raw) if montant_prevu_raw else None
            montant_paye = Decimal(montant_paye_raw) if montant_paye_raw else Decimal("0.00")
        except InvalidOperation:
            context["error"] = "Les montants saisis sont invalides."
            return render(request, "joatham_apprenants/inscription_form.html", context, status=400)

        inscrire_apprenant_a_formation(
            entreprise=entreprise,
            apprenant_id=request.POST.get("apprenant"),
            formation_id=request.POST.get("formation"),
            statut=request.POST.get("statut") or InscriptionFormation.Statut.EN_COURS,
            montant_prevu=montant_prevu,
            montant_paye=montant_paye,
            utilisateur=request.user,
        )
        return redirect("apprenant_list")

    return render(request, "joatham_apprenants/inscription_form.html", context)


@permission_required("apprenants.view")
def inscription_detail(request, inscription_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)
    paiements = get_paiements_by_inscription(entreprise, inscription)
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


@permission_required("apprenants.payments")
def paiement_inscription_create(request, inscription_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)
    paiements = get_paiements_by_inscription(entreprise, inscription)
    context = {
        "entreprise": entreprise,
        "inscription": inscription,
        "paiements": paiements,
        "modes_paiement": PaiementInscription.ModePaiement.choices,
    }

    if request.method == "POST":
        try:
            montant = Decimal(request.POST.get("montant", "0") or "0")
        except InvalidOperation:
            context["error"] = "Le montant saisi est invalide."
            return render(request, "joatham_apprenants/paiement_form.html", context, status=400)

        create_paiement_inscription(
            entreprise=entreprise,
            inscription_id=inscription.id,
            montant=montant,
            mode_paiement=request.POST.get("mode_paiement"),
            reference=request.POST.get("reference", ""),
            observations=request.POST.get("observations", ""),
            utilisateur=request.user,
        )
        return redirect("inscription_detail", inscription_id=inscription.id)

    return render(request, "joatham_apprenants/paiement_form.html", context)


@permission_required("apprenants.manage")
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
            messages.success(request, f"La facture {facture.numero} a été créée et liée à l'inscription.")
        except (ValidationError, FacturationError) as exc:
            messages.error(request, str(exc))

    return redirect("inscription_detail", inscription_id=inscription.id)


@permission_required("apprenants.manage")
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
            messages.success(request, f"La facture {facture.numero} a été liée à l'inscription.")
        except (ValidationError, FacturationError) as exc:
            messages.error(request, str(exc))

    return redirect("inscription_detail", inscription_id=inscription.id)


@permission_required("apprenants.manage")
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
            messages.success(request, f"La facture {facture.numero} a été déliée de l'inscription.")
        except (ValidationError, FacturationError) as exc:
            messages.error(request, str(exc))

    return redirect("inscription_detail", inscription_id=inscription.id)


@permission_required("apprenants.view")
def apprenants_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    apprenants = get_apprenants_by_entreprise(entreprise)
    context = {
        "apprenants": apprenants,
        **build_report_metadata(entreprise=entreprise, title="Liste des apprenants"),
    }
    return render_pdf_response(
        request,
        "joatham_apprenants/apprenants_pdf.html",
        context,
        filename="apprenants.pdf",
        disposition="attachment",
    )


@permission_required("apprenants.view")
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
            "Oui" if apprenant.actif else "Non",
        ]
        for apprenant in apprenants
    ]
    return build_xlsx_response(
        filename="apprenants.xlsx",
        sheet_name="Apprenants",
        headers=["Nom", "Prenom", "Telephone", "Email", "Date inscription", "Actif"],
        rows=rows,
    )


@permission_required("apprenants.view")
def formations_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    formations = get_formations_by_entreprise(entreprise)
    context = {
        "formations": formations,
        **build_report_metadata(entreprise=entreprise, title="Liste des formations"),
    }
    return render_pdf_response(
        request,
        "joatham_apprenants/formations_pdf.html",
        context,
        filename="formations.pdf",
        disposition="attachment",
    )


@permission_required("apprenants.view")
def formations_excel(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    formations = get_formations_by_entreprise(entreprise)
    rows = [
        [formation.nom, formation.description, formation.prix, formation.duree, "Oui" if formation.actif else "Non"]
        for formation in formations
    ]
    return build_xlsx_response(
        filename="formations.xlsx",
        sheet_name="Formations",
        headers=["Nom", "Description", "Prix", "Duree", "Actif"],
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
def inscriptions_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscriptions = _get_inscriptions_export_queryset(request, entreprise)
    context = {
        "inscriptions": inscriptions,
        **build_report_metadata(entreprise=entreprise, title="Liste des inscriptions"),
    }
    return render_pdf_response(
        request,
        "joatham_apprenants/inscriptions_pdf.html",
        context,
        filename="inscriptions.pdf",
        disposition="attachment",
    )


@permission_required("apprenants.view")
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
        ]
        for inscription in inscriptions
    ]
    return build_xlsx_response(
        filename="inscriptions.xlsx",
        sheet_name="Inscriptions",
        headers=["Apprenant", "Formation", "Date inscription", "Statut", "Montant prevu", "Montant paye", "Solde"],
        rows=rows,
    )


@permission_required("apprenants.view")
def inscription_paiements_pdf(request, inscription_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    inscription = get_inscription_by_entreprise(entreprise, inscription_id)
    paiements = get_paiements_by_inscription(entreprise, inscription)
    context = {
        "inscription": inscription,
        "paiements": paiements,
        **build_report_metadata(entreprise=entreprise, title="Historique des paiements"),
    }
    return render_pdf_response(
        request,
        "joatham_apprenants/paiements_inscription_pdf.html",
        context,
        filename=f"inscription-{inscription.id}-paiements.pdf",
        disposition="attachment",
    )


@permission_required("apprenants.view")
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
        headers=["Date paiement", "Montant", "Mode", "Reference", "Utilisateur", "Observations"],
        rows=rows,
    )


@permission_required("apprenants.view")
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
        **build_report_metadata(entreprise=entreprise, title="Synthese dashboard apprenants"),
    }
    return render_pdf_response(
        request,
        "joatham_apprenants/dashboard_pdf.html",
        context,
        filename="dashboard-apprenants.pdf",
        disposition="attachment",
    )


@permission_required("apprenants.view")
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
        headers=["Indicateur", "Valeur"],
        rows=rows,
    )
