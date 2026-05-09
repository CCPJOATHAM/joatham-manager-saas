from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date

from core.services.quotas import PlanQuotaExceeded
from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_apprenants.services.export_service import build_report_metadata, build_xlsx_response
from joatham_billing.pdf import render_pdf_response
from joatham_users.permissions import permission_required, user_has_permission

from .forms import CaisseForm, CloseSessionForm, MouvementCaisseForm, OpenSessionForm, SessionDecisionForm
from .models import MouvementCaisse, SessionCaisse
from .selectors.caisse import get_caisses_by_entreprise, get_caisse_by_entreprise
from .selectors.dashboard import get_cash_dashboard_snapshot
from .selectors.mouvements import get_cash_flow_totals_for_session, get_mouvements_for_entreprise, get_mouvements_for_session
from .selectors.session import get_open_session_for_caisse, get_session_by_entreprise, get_sessions_by_entreprise
from .selectors.reports import get_cash_report_snapshot
from .services.caisse import create_caisse, list_caisses_for_entreprise
from .services.mouvements import record_adjustment, record_cash_entry, record_cash_exit, record_cash_expense
from .services.session import close_session, open_session
from .services.validation import reject_session, validate_session


def _parse_int(raw_value):
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _parse_decimal(raw_value):
    if raw_value in (None, ""):
        return None
    try:
        return Decimal(str(raw_value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_bool(raw_value):
    return str(raw_value).lower() in {"1", "true", "on", "yes"}


def _resolve_caisse_filter(entreprise, raw_value):
    caisse_id = _parse_int(raw_value)
    if not caisse_id:
        return None
    return get_caisses_by_entreprise(entreprise).filter(id=caisse_id).first()


def _resolve_session_filter(entreprise, raw_value):
    session_id = _parse_int(raw_value)
    if not session_id:
        return None
    return get_sessions_by_entreprise(entreprise).filter(id=session_id).first()


def _resolve_opening_user_filter(entreprise, raw_value):
    user_id = _parse_int(raw_value)
    if not user_id:
        return None
    return get_sessions_by_entreprise(entreprise).filter(utilisateur_ouverture_id=user_id).first()


def _get_opening_user_options(entreprise):
    users = []
    seen_ids = set()
    for cash_session in get_sessions_by_entreprise(entreprise):
        user = cash_session.utilisateur_ouverture
        if user and user.id not in seen_ids:
            users.append(user)
            seen_ids.add(user.id)
    return users


def _build_period_label(date_debut_raw, date_fin_raw):
    if date_debut_raw and date_fin_raw:
        return f"Periode du {date_debut_raw} au {date_fin_raw}"
    if date_debut_raw:
        return f"Periode a partir du {date_debut_raw}"
    if date_fin_raw:
        return f"Periode jusqu'au {date_fin_raw}"
    return "Toutes les donnees disponibles"


def _get_movement_filters_from_request(request, entreprise):
    selected_caisse = _resolve_caisse_filter(entreprise, request.GET.get("caisse"))
    available_sessions = list(get_sessions_by_entreprise(entreprise, caisse=selected_caisse)[:100])
    selected_session = _resolve_session_filter(entreprise, request.GET.get("session"))
    if selected_session and selected_caisse and selected_session.caisse_id != selected_caisse.id:
        selected_session = None
    type_mouvement = (request.GET.get("type_mouvement") or "").strip()
    q = (request.GET.get("q") or "").strip()
    raw_date_debut = request.GET.get("date_debut", "")
    raw_date_fin = request.GET.get("date_fin", "")
    raw_montant_min = request.GET.get("montant_min", "")
    raw_montant_max = request.GET.get("montant_max", "")
    return {
        "selected_caisse": selected_caisse,
        "available_sessions": available_sessions,
        "selected_session": selected_session,
        "type_mouvement": type_mouvement,
        "date_debut": parse_date(raw_date_debut or ""),
        "date_fin": parse_date(raw_date_fin or ""),
        "montant_min": _parse_decimal(raw_montant_min),
        "montant_max": _parse_decimal(raw_montant_max),
        "q": q,
        "raw": {
            "caisse": selected_caisse.id if selected_caisse else "",
            "session": selected_session.id if selected_session else "",
            "type_mouvement": type_mouvement,
            "date_debut": raw_date_debut,
            "date_fin": raw_date_fin,
            "montant_min": raw_montant_min,
            "montant_max": raw_montant_max,
            "q": q,
        },
        "query_string": request.GET.urlencode(),
    }


def _get_report_filters_from_request(request, entreprise):
    selected_caisse = _resolve_caisse_filter(entreprise, request.GET.get("caisse"))
    raw_date_debut = request.GET.get("date_debut", "")
    raw_date_fin = request.GET.get("date_fin", "")
    return {
        "selected_caisse": selected_caisse,
        "date_debut": parse_date(raw_date_debut or ""),
        "date_fin": parse_date(raw_date_fin or ""),
        "raw": {
            "caisse": selected_caisse.id if selected_caisse else "",
            "date_debut": raw_date_debut,
            "date_fin": raw_date_fin,
        },
        "period_label": _build_period_label(raw_date_debut, raw_date_fin),
        "query_string": request.GET.urlencode(),
    }


@permission_required("caisse.view")
@module_access_required("caisse")
def caisse_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    dashboard = get_cash_dashboard_snapshot(entreprise)
    return render(
        request,
        "joatham_caisse/caisse_list.html",
        {
            "caisses": list(list_caisses_for_entreprise(entreprise)),
            "dashboard": dashboard,
            "sessions_recentes": dashboard["open_sessions"],
            "can_create_caisse": user_has_permission(request.user, "caisse.create"),
            "can_open_session": user_has_permission(request.user, "caisse.open_session"),
            "can_add_movement": user_has_permission(request.user, "caisse.add_movement"),
        },
    )


@permission_required("caisse.view")
@module_access_required("caisse")
def session_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    caisses = list(get_caisses_by_entreprise(entreprise))
    selected_caisse = _resolve_caisse_filter(entreprise, request.GET.get("caisse"))
    statut = (request.GET.get("statut") or "").strip()
    date_debut = parse_date(request.GET.get("date_debut") or "")
    date_fin = parse_date(request.GET.get("date_fin") or "")
    user_session = _resolve_opening_user_filter(entreprise, request.GET.get("utilisateur_ouverture"))
    selected_user = user_session.utilisateur_ouverture if user_session else None
    avec_ecart = _parse_bool(request.GET.get("avec_ecart"))
    sessions = get_sessions_by_entreprise(
        entreprise,
        caisse=selected_caisse,
        statut=statut or None,
        date_debut=date_debut,
        date_fin=date_fin,
        utilisateur_ouverture=selected_user,
        avec_ecart=avec_ecart,
    )
    session_count = sessions.count()
    return render(
        request,
        "joatham_caisse/session_list.html",
        {
            "sessions": sessions,
            "caisses": caisses,
            "opening_users": _get_opening_user_options(entreprise),
            "status_choices": SessionCaisse.Statut.choices,
            "filters": {
                "caisse": selected_caisse.id if selected_caisse else "",
                "statut": statut,
                "date_debut": request.GET.get("date_debut", ""),
                "date_fin": request.GET.get("date_fin", ""),
                "utilisateur_ouverture": selected_user.id if selected_user else "",
                "avec_ecart": avec_ecart,
            },
            "session_counts": {
                "total": session_count,
                "open": sessions.filter(statut=SessionCaisse.Statut.OUVERTE).count(),
                "with_ecart": sessions.exclude(ecart=0).count(),
            },
        },
    )


@permission_required("caisse.view")
@module_access_required("caisse")
def movement_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    caisses = list(get_caisses_by_entreprise(entreprise))
    movement_filters = _get_movement_filters_from_request(request, entreprise)
    movements = get_mouvements_for_entreprise(
        entreprise,
        caisse=movement_filters["selected_caisse"],
        session=movement_filters["selected_session"],
        type_mouvement=movement_filters["type_mouvement"] or None,
        date_debut=movement_filters["date_debut"],
        date_fin=movement_filters["date_fin"],
        montant_min=movement_filters["montant_min"],
        montant_max=movement_filters["montant_max"],
        q=movement_filters["q"],
    )
    return render(
        request,
        "joatham_caisse/movement_list.html",
        {
            "movements": movements,
            "caisses": caisses,
            "sessions": movement_filters["available_sessions"],
            "movement_type_choices": MouvementCaisse.TypeMouvement.choices,
            "filters": movement_filters["raw"],
            "filter_query": movement_filters["query_string"],
        },
    )


@permission_required("caisse.dashboard")
@module_access_required("caisse")
def cash_reports(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    caisses = list(get_caisses_by_entreprise(entreprise))
    report_filters = _get_report_filters_from_request(request, entreprise)
    report = get_cash_report_snapshot(
        entreprise,
        caisse=report_filters["selected_caisse"],
        date_debut=report_filters["date_debut"],
        date_fin=report_filters["date_fin"],
    )
    return render(
        request,
        "joatham_caisse/reports.html",
        {
            "report": report,
            "caisses": caisses,
            "filters": report_filters["raw"],
            "filter_query": report_filters["query_string"],
        },
    )


@permission_required("caisse.export")
@module_access_required("caisse")
def movement_export_excel(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    movement_filters = _get_movement_filters_from_request(request, entreprise)
    movements = get_mouvements_for_entreprise(
        entreprise,
        caisse=movement_filters["selected_caisse"],
        session=movement_filters["selected_session"],
        type_mouvement=movement_filters["type_mouvement"] or None,
        date_debut=movement_filters["date_debut"],
        date_fin=movement_filters["date_fin"],
        montant_min=movement_filters["montant_min"],
        montant_max=movement_filters["montant_max"],
        q=movement_filters["q"],
    )
    rows = [
        [
            movement.date_mouvement.strftime("%d/%m/%Y %H:%M"),
            movement.caisse.nom,
            f"{movement.session.id} - {movement.session.date_ouverture.strftime('%d/%m/%Y %H:%M')}",
            movement.get_type_mouvement_display(),
            movement.montant,
            movement.devise,
            movement.libelle,
            movement.reference,
            movement.get_statut_display(),
            str(movement.cree_par or "-"),
        ]
        for movement in movements
    ]
    return build_xlsx_response(
        filename="mouvements-caisse.xlsx",
        sheet_name="Mouvements caisse",
        headers=[
            "Date",
            "Caisse",
            "Session",
            "Type",
            "Montant",
            "Devise",
            "Libelle",
            "Reference",
            "Statut",
            "Utilisateur",
        ],
        rows=rows,
    )


@permission_required("caisse.export")
@module_access_required("caisse")
def cash_reports_export_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    report_filters = _get_report_filters_from_request(request, entreprise)
    report = get_cash_report_snapshot(
        entreprise,
        caisse=report_filters["selected_caisse"],
        date_debut=report_filters["date_debut"],
        date_fin=report_filters["date_fin"],
    )
    recent_movements = list(
        get_mouvements_for_entreprise(
            entreprise,
            caisse=report_filters["selected_caisse"],
            date_debut=report_filters["date_debut"],
            date_fin=report_filters["date_fin"],
        )[:20]
    )
    context = {
        "entreprise": entreprise,
        "selected_caisse": report_filters["selected_caisse"],
        "period_label": report_filters["period_label"],
        "report": report,
        "recent_movements": recent_movements,
        **build_report_metadata(entreprise=entreprise, title="Rapport caisse"),
    }
    return render_pdf_response(
        request,
        "joatham_caisse/reports_pdf.html",
        context,
        filename="rapport-caisse.pdf",
        disposition="attachment",
    )


@permission_required("caisse.create")
@module_access_required("caisse")
def caisse_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = CaisseForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            caisse = create_caisse(entreprise=entreprise, utilisateur=request.user, **form.cleaned_data)
        except (PlanQuotaExceeded, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "La caisse a ete creee avec succes.")
            return redirect("caisse_detail", caisse_id=caisse.id)

    return render(
        request,
        "joatham_caisse/caisse_form.html",
        {"form": form, "page_title": "Nouvelle caisse", "submit_label": "Creer la caisse"},
    )


@permission_required("caisse.view")
@module_access_required("caisse")
def caisse_detail(request, caisse_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    caisse = get_caisse_by_entreprise(entreprise, caisse_id)
    open_cash_session = get_open_session_for_caisse(caisse)
    sessions = get_sessions_by_entreprise(entreprise, caisse=caisse)[:20]
    recent_movements = get_mouvements_for_entreprise(entreprise, caisse=caisse)[:8]
    return render(
        request,
        "joatham_caisse/caisse_detail.html",
        {
            "caisse": caisse,
            "open_cash_session": open_cash_session,
            "sessions": sessions,
            "recent_movements": recent_movements,
            "can_open_session": user_has_permission(request.user, "caisse.open_session"),
        },
    )


@permission_required("caisse.open_session")
@module_access_required("caisse")
def open_session_view(request, caisse_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    caisse = get_caisse_by_entreprise(entreprise, caisse_id)
    form = OpenSessionForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            session = open_session(
                entreprise=entreprise,
                caisse=caisse,
                utilisateur=request.user,
                solde_initial=form.cleaned_data["solde_initial"],
                commentaire=form.cleaned_data["commentaire_ouverture"],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "La session de caisse a ete ouverte.")
            return redirect("caisse_session_detail", session_id=session.id)

    return render(
        request,
        "joatham_caisse/session_open.html",
        {"form": form, "caisse": caisse},
    )


@permission_required("caisse.view")
@module_access_required("caisse")
def session_detail(request, session_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    session = get_session_by_entreprise(entreprise, session_id)
    movement_totals = get_cash_flow_totals_for_session(session)
    movements = get_mouvements_for_session(session)
    decision_form = SessionDecisionForm()
    return render(
        request,
        "joatham_caisse/session_detail.html",
        {
            "session": session,
            "movements": movements,
            "movement_totals": movement_totals,
            "decision_form": decision_form,
            "solde_reel_display": session.solde_reel if session.solde_reel is not None else "-",
            "can_add_movement": user_has_permission(request.user, "caisse.add_movement"),
            "can_close_session": user_has_permission(request.user, "caisse.close_session"),
            "can_validate_session": user_has_permission(request.user, "caisse.validate_session"),
            "can_reject_session": user_has_permission(request.user, "caisse.reject_session"),
        },
    )


@permission_required("caisse.close_session")
@module_access_required("caisse")
def close_session_view(request, session_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    session = get_session_by_entreprise(entreprise, session_id)
    form = CloseSessionForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            close_session(
                entreprise=entreprise,
                session=session,
                utilisateur=request.user,
                solde_reel=form.cleaned_data["solde_reel"],
                commentaire=form.cleaned_data["commentaire_fermeture"],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "La session de caisse a ete fermee.")
            return redirect("caisse_session_detail", session_id=session.id)

    return render(
        request,
        "joatham_caisse/session_close.html",
        {"form": form, "session": session},
    )


@permission_required("caisse.add_movement")
@module_access_required("caisse")
def add_movement_view(request, session_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    session = get_session_by_entreprise(entreprise, session_id)
    form = MouvementCaisseForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            movement_type = form.cleaned_data["type_mouvement"]
            payload = {
                "entreprise": entreprise,
                "caisse": session.caisse,
                "session": session,
                "montant": form.cleaned_data["montant"],
                "libelle": form.cleaned_data["libelle"],
                "reference": form.cleaned_data["reference"],
                "commentaire": form.cleaned_data["commentaire"],
                "utilisateur": request.user,
            }
            if movement_type == "entree":
                record_cash_entry(**payload)
            elif movement_type == "sortie":
                record_cash_exit(**payload)
            elif movement_type == "depense":
                record_cash_expense(**payload)
            else:
                record_adjustment(**payload)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Le mouvement de caisse a ete enregistre.")
            return redirect("caisse_session_detail", session_id=session.id)

    return render(
        request,
        "joatham_caisse/mouvement_form.html",
        {"form": form, "session": session},
    )


@permission_required("caisse.validate_session")
@module_access_required("caisse")
def validate_session_view(request, session_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    session = get_session_by_entreprise(entreprise, session_id)
    if request.method != "POST":
        return redirect("caisse_session_detail", session_id=session.id)

    form = SessionDecisionForm(request.POST)
    if form.is_valid():
        try:
            validate_session(
                entreprise=entreprise,
                session=session,
                utilisateur=request.user,
                commentaire=form.cleaned_data["commentaire"],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "La session a ete validee.")
    return redirect("caisse_session_detail", session_id=session.id)


@permission_required("caisse.reject_session")
@module_access_required("caisse")
def reject_session_view(request, session_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    session = get_session_by_entreprise(entreprise, session_id)
    if request.method != "POST":
        return redirect("caisse_session_detail", session_id=session.id)

    form = SessionDecisionForm(request.POST)
    if form.is_valid():
        try:
            reject_session(
                entreprise=entreprise,
                session=session,
                utilisateur=request.user,
                commentaire=form.cleaned_data["commentaire"],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "La session a ete rejetee.")
    return redirect("caisse_session_detail", session_id=session.id)
