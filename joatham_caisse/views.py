from django.contrib import messages
from django.shortcuts import redirect, render

from core.services.quotas import PlanQuotaExceeded
from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.permissions import permission_required, user_has_permission

from .forms import CaisseForm, CloseSessionForm, MouvementCaisseForm, OpenSessionForm, SessionDecisionForm
from .selectors.caisse import get_caisse_by_entreprise
from .selectors.dashboard import get_cash_dashboard_snapshot
from .selectors.mouvements import get_cash_flow_totals_for_session, get_mouvements_for_entreprise, get_mouvements_for_session
from .selectors.session import get_open_session_for_caisse, get_session_by_entreprise, get_sessions_by_entreprise
from .services.caisse import create_caisse, list_caisses_for_entreprise
from .services.mouvements import record_adjustment, record_cash_entry, record_cash_exit, record_cash_expense
from .services.session import close_session, open_session
from .services.validation import reject_session, validate_session


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
