from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _

from joatham_apprenants.services.export_service import build_report_metadata, build_xlsx_response
from joatham_billing.pdf import render_pdf_response
from core.services.quotas import PlanQuotaExceeded
from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.permissions import permission_required, require_permission, user_has_permission

from .forms import (
    InventoryCountFormSet,
    InventorySessionForm,
    ProduitCreateForm,
    ProduitUpdateForm,
    StockMovementForm,
)
from .models import StockMovement
from .selectors.products import (
    STOCK_FILTER_ALL,
    STOCK_FILTER_LOW,
    STOCK_FILTER_RUPTURE,
    get_product_by_entreprise,
    get_product_counts_by_entreprise,
)
from .selectors.inventory import (
    get_inventory_lines_for_session,
    get_inventory_session_for_entreprise,
    get_inventory_sessions_for_entreprise,
    get_inventory_summary,
)
from .selectors.reports import (
    get_recent_stock_activity,
    get_stock_report_inventory_summary,
    get_stock_report_movement_type_summary,
    get_stock_report_product_summary,
    get_stock_report_snapshot,
)
from .selectors.stock import get_stock_movements_for_entreprise
from .services.inventory import (
    InventoryOperationError,
    cancel_inventory_session,
    close_inventory_session,
    create_inventory_session,
    record_inventory_count,
    start_inventory_session,
    validate_inventory_session,
)
from .services.products_service import create_product_for_entreprise, list_products_for_entreprise, update_product_for_entreprise
from .services.stock import StockOperationError, apply_adjustment, apply_manual_entry, apply_manual_exit


def _build_product_ui_permissions(user):
    return {
        "can_manage_products_ui": user_has_permission(user, "products.manage"),
        "can_view_stock_ui": user_has_permission(user, "stock.view"),
        "can_move_stock_ui": user_has_permission(user, "stock.move"),
        "can_adjust_stock_ui": user_has_permission(user, "stock.adjust"),
        "can_inventory_stock_ui": user_has_permission(user, "stock.inventory"),
        "can_export_stock_ui": user_has_permission(user, "stock.export"),
    }


def _build_stock_type_label(movement_type):
    return {
        StockMovement.MovementType.MANUAL_ENTRY: _("Entree"),
        StockMovement.MovementType.MANUAL_EXIT: _("Sortie"),
        StockMovement.MovementType.ADJUSTMENT_POSITIVE: _("Ajustement +"),
        StockMovement.MovementType.ADJUSTMENT_NEGATIVE: _("Ajustement -"),
        StockMovement.MovementType.INVOICE_SALE: _("Vente facture"),
        StockMovement.MovementType.INVOICE_RESTORE: _("Restauration facture"),
        StockMovement.MovementType.INVENTORY_RECOUNT: _("Inventaire"),
        StockMovement.MovementType.TRANSFER_OUT: _("Transfert sortant"),
        StockMovement.MovementType.TRANSFER_IN: _("Transfert entrant"),
    }.get(movement_type, movement_type)


def _build_inventory_status_label(status):
    return {
        "draft": _("Brouillon"),
        "in_progress": _("En cours"),
        "closed": _("Cloture"),
        "validated": _("Valide"),
        "cancelled": _("Annule"),
    }.get(status, status)


def _get_stock_filters_from_request(request, entreprise):
    product_id = (request.GET.get("produit") or "").strip()
    movement_type = (request.GET.get("movement_type") or "").strip()
    source_app = (request.GET.get("source_app") or "").strip()
    date_debut = parse_date((request.GET.get("date_debut") or "").strip()) if request.GET.get("date_debut") else None
    date_fin = parse_date((request.GET.get("date_fin") or "").strip()) if request.GET.get("date_fin") else None

    produit = None
    if product_id:
        produit = get_product_by_entreprise(entreprise, product_id)

    return {
        "produit": produit,
        "movement_type": movement_type or None,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "source_app": source_app or None,
        "selected_product_id": str(product_id) if product_id else "",
        "selected_movement_type": movement_type,
        "selected_source_app": source_app,
        "selected_date_debut": request.GET.get("date_debut", ""),
        "selected_date_fin": request.GET.get("date_fin", ""),
    }


def _get_inventory_filters_from_request(request):
    status = (request.GET.get("status") or "").strip()
    date_debut = parse_date((request.GET.get("date_debut") or "").strip()) if request.GET.get("date_debut") else None
    date_fin = parse_date((request.GET.get("date_fin") or "").strip()) if request.GET.get("date_fin") else None
    return {
        "status": status or None,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "selected_status": status,
        "selected_date_debut": request.GET.get("date_debut", ""),
        "selected_date_fin": request.GET.get("date_fin", ""),
    }


def _build_stock_operation_context(*, form, page_title, submit_label, help_text):
    return {
        "form": form,
        "page_title": page_title,
        "submit_label": submit_label,
        "help_text": help_text,
        "back_url": "stock_movement_list",
    }


def _build_inventory_lines_data(lines):
    return [
        {
            "instance": line,
            "difference_label": f"{line.difference:+d}" if line.counted_quantity is not None else "-",
        }
        for line in lines
    ]


def _normalize_stock_report_filters(filters):
    return {
        "produit": filters["produit"],
        "movement_type": filters["movement_type"],
        "date_debut": filters["date_debut"],
        "date_fin": filters["date_fin"],
        "source_app": filters["source_app"],
    }


def _handle_stock_operation(*, request, entreprise, form, operation):
    if request.method != "POST" or not form.is_valid():
        return None

    data = form.cleaned_data
    try:
        if operation == "entry":
            apply_manual_entry(
                entreprise=entreprise,
                produit=data["produit"],
                quantity=data["quantity"],
                utilisateur=request.user,
                reference=data["reference"],
                reason=data["reason"],
                comment=data["comment"],
            )
        elif operation == "exit":
            apply_manual_exit(
                entreprise=entreprise,
                produit=data["produit"],
                quantity=data["quantity"],
                utilisateur=request.user,
                reference=data["reference"],
                reason=data["reason"],
                comment=data["comment"],
            )
        elif operation == "adjustment":
            apply_adjustment(
                entreprise=entreprise,
                produit=data["produit"],
                quantity=data["quantity"],
                movement_type=data["movement_type"],
                utilisateur=request.user,
                reference=data["reference"],
                reason=data["reason"],
                comment=data["comment"],
            )
        else:
            raise PermissionDenied("Operation de stock invalide.")
    except StockOperationError as exc:
        form.add_error(None, str(exc))
        return None

    messages.success(request, _("Le mouvement de stock a ete enregistre avec succes."))
    return redirect("stock_movement_list")


@permission_required("products.view")
@module_access_required("products")
def product_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    selected_filter = (request.GET.get("stock") or STOCK_FILTER_ALL).strip() or STOCK_FILTER_ALL
    products = list_products_for_entreprise(
        entreprise,
        stock_filter=None if selected_filter == STOCK_FILTER_ALL else selected_filter,
    )
    counts = get_product_counts_by_entreprise(entreprise)

    product_rows = [
        {
            "instance": produit,
            "status": produit.stock_status,
            "status_label": {
                "en_stock": _("En stock"),
                "stock_faible": _("Stock faible"),
                "rupture": _("Rupture"),
            }[produit.stock_status],
        }
        for produit in products
    ]

    return render(
        request,
        "joatham_products/product_list.html",
        {
            "products": product_rows,
            "selected_filter": selected_filter,
            "filters": [
                {"value": STOCK_FILTER_ALL, "label": _("Tous")},
                {"value": STOCK_FILTER_LOW, "label": _("Stock faible")},
                {"value": STOCK_FILTER_RUPTURE, "label": _("Rupture")},
            ],
            **counts,
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("products.manage")
@module_access_required("products")
def product_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = ProduitCreateForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            create_product_for_entreprise(
                entreprise=entreprise,
                utilisateur=request.user,
                **form.cleaned_data,
            )
        except PlanQuotaExceeded as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Le produit a ete cree avec succes."))
            return redirect("product_list")

    return render(
        request,
        "joatham_products/product_form.html",
        {
            "form": form,
            "page_title": _("Creer un produit"),
            "submit_label": _("Creer le produit"),
            "is_create_mode": True,
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("products.view")
@module_access_required("products")
def product_update(request, product_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    produit = get_product_by_entreprise(entreprise, product_id)
    require_permission(request.user, "products.manage")
    form = ProduitUpdateForm(request.POST or None, instance=produit)

    if request.method == "POST" and form.is_valid():
        update_product_for_entreprise(
            entreprise=entreprise,
            product_id=produit.id,
            utilisateur=request.user,
            quantite_stock=produit.quantite_stock,
            **form.cleaned_data,
        )
        messages.success(request, _("Le produit a ete mis a jour avec succes."))
        return redirect("product_list")

    return render(
        request,
        "joatham_products/product_form.html",
        {
            "form": form,
            "page_title": _("Modifier un produit"),
            "submit_label": _("Enregistrer les modifications"),
            "product": produit,
            "is_create_mode": False,
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("stock.view")
@module_access_required("products")
def stock_movement_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    filters = _get_stock_filters_from_request(request, entreprise)
    movements = get_stock_movements_for_entreprise(
        entreprise,
        produit=filters["produit"],
        movement_type=filters["movement_type"],
        date_debut=filters["date_debut"],
        date_fin=filters["date_fin"],
        source_app=filters["source_app"],
    )
    products = list_products_for_entreprise(entreprise)
    rows = [
        {
            "instance": movement,
            "type_label": _build_stock_type_label(movement.movement_type),
        }
        for movement in movements
    ]

    return render(
        request,
        "joatham_products/stock_movement_list.html",
        {
            "movements": rows,
            "products": products,
            "movement_types": [
                (StockMovement.MovementType.MANUAL_ENTRY, _("Entree")),
                (StockMovement.MovementType.MANUAL_EXIT, _("Sortie")),
                (StockMovement.MovementType.ADJUSTMENT_POSITIVE, _("Ajustement +")),
                (StockMovement.MovementType.ADJUSTMENT_NEGATIVE, _("Ajustement -")),
                (StockMovement.MovementType.INVOICE_SALE, _("Vente facture")),
                (StockMovement.MovementType.INVOICE_RESTORE, _("Restauration facture")),
            ],
            "source_choices": [
                ("", _("Toutes les sources")),
                ("joatham_billing", _("Facturation")),
                ("joatham_products", _("Produits / inventaire")),
            ],
            **filters,
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("stock.view")
@module_access_required("products")
def stock_reports(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    filters = _get_stock_filters_from_request(request, entreprise)
    report_filters = _normalize_stock_report_filters(filters)
    report = get_stock_report_snapshot(entreprise, **report_filters)
    product_summary = get_stock_report_product_summary(entreprise, **report_filters)
    movement_type_summary = get_stock_report_movement_type_summary(entreprise, **report_filters)
    inventory_summary = get_stock_report_inventory_summary(
        entreprise,
        date_debut=filters["date_debut"],
        date_fin=filters["date_fin"],
    )
    recent_movements = get_recent_stock_activity(entreprise, limit=20, **report_filters)
    products = list_products_for_entreprise(entreprise)

    return render(
        request,
        "joatham_products/stock_reports.html",
        {
            "report": report,
            "product_summary": product_summary,
            "movement_type_summary": movement_type_summary,
            "inventory_summary": inventory_summary,
            "recent_movements": recent_movements,
            "products": products,
            "movement_types": [
                (StockMovement.MovementType.MANUAL_ENTRY, _("Entree")),
                (StockMovement.MovementType.MANUAL_EXIT, _("Sortie")),
                (StockMovement.MovementType.ADJUSTMENT_POSITIVE, _("Ajustement +")),
                (StockMovement.MovementType.ADJUSTMENT_NEGATIVE, _("Ajustement -")),
                (StockMovement.MovementType.INVOICE_SALE, _("Vente facture")),
                (StockMovement.MovementType.INVOICE_RESTORE, _("Restauration facture")),
            ],
            "source_choices": [
                ("", _("Toutes les sources")),
                ("joatham_billing", _("Facturation")),
                ("joatham_products", _("Produits / inventaire")),
            ],
            **filters,
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("stock.export")
@module_access_required("products")
def stock_movement_export_excel(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    filters = _get_stock_filters_from_request(request, entreprise)
    movements = get_stock_movements_for_entreprise(
        entreprise,
        produit=filters["produit"],
        movement_type=filters["movement_type"],
        date_debut=filters["date_debut"],
        date_fin=filters["date_fin"],
        source_app=filters["source_app"],
    )
    rows = [
        [
            movement.created_at.strftime("%d/%m/%Y %H:%M"),
            movement.produit.nom,
            _build_stock_type_label(movement.movement_type),
            movement.quantity,
            movement.stock_before,
            movement.stock_after,
            movement.reference,
            movement.reason,
            movement.comment,
            movement.source_app,
            movement.source_model,
            movement.source_id if movement.source_id is not None else "",
            movement.created_by.username if movement.created_by else "",
        ]
        for movement in movements
    ]
    return build_xlsx_response(
        filename="mouvements-stock.xlsx",
        sheet_name="Mouvements stock",
        headers=[
            "Date",
            "Produit",
            "Type",
            "Quantite",
            "Stock avant",
            "Stock apres",
            "Reference",
            "Motif",
            "Commentaire",
            "Source app",
            "Source model",
            "Source id",
            "Utilisateur",
        ],
        rows=rows,
    )


@permission_required("stock.export")
@module_access_required("products")
def inventory_export_excel(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    filters = _get_inventory_filters_from_request(request)
    sessions = get_inventory_sessions_for_entreprise(
        entreprise,
        status=filters["status"],
        date_debut=filters["date_debut"],
        date_fin=filters["date_fin"],
    )
    session_ids = list(sessions.values_list("id", flat=True))
    lines = []
    for session in sessions:
        lines.extend(get_inventory_lines_for_session(entreprise, session))

    rows = [
        [
            line.session.name,
            _build_inventory_status_label(line.session.status),
            line.produit.nom,
            line.theoretical_quantity,
            line.counted_quantity if line.counted_quantity is not None else "",
            line.difference,
            line.comment,
            line.session.created_at.strftime("%d/%m/%Y %H:%M"),
            line.session.validated_at.strftime("%d/%m/%Y %H:%M") if line.session.validated_at else "",
        ]
        for line in lines
        if line.session_id in session_ids
    ]
    return build_xlsx_response(
        filename="inventaires-stock.xlsx",
        sheet_name="Inventaires stock",
        headers=[
            "Session",
            "Statut",
            "Produit",
            "Stock theorique",
            "Quantite comptee",
            "Ecart",
            "Commentaire ligne",
            "Date creation session",
            "Date validation",
        ],
        rows=rows,
    )


@permission_required("stock.export")
@module_access_required("products")
def stock_reports_export_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    filters = _get_stock_filters_from_request(request, entreprise)
    report_filters = _normalize_stock_report_filters(filters)
    report = get_stock_report_snapshot(entreprise, **report_filters)
    product_summary = get_stock_report_product_summary(entreprise, **report_filters)
    movement_type_summary = get_stock_report_movement_type_summary(entreprise, **report_filters)
    inventory_summary = get_stock_report_inventory_summary(
        entreprise,
        date_debut=filters["date_debut"],
        date_fin=filters["date_fin"],
    )
    recent_movements = get_recent_stock_activity(entreprise, limit=20, **report_filters)
    context = {
        **build_report_metadata(entreprise=entreprise, title="Rapport stock"),
        "report": report,
        "product_summary": product_summary,
        "movement_type_summary": movement_type_summary,
        "inventory_summary": inventory_summary,
        "recent_movements": recent_movements,
        "selected_date_debut": filters["selected_date_debut"],
        "selected_date_fin": filters["selected_date_fin"],
        "selected_product_name": filters["produit"].nom if filters["produit"] else "",
    }
    return render_pdf_response(
        request,
        "joatham_products/stock_reports_pdf.html",
        context,
        "rapport-stock.pdf",
        disposition="attachment",
    )


@permission_required("stock.move")
@module_access_required("products")
def stock_entry_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = StockMovementForm(
        request.POST or None,
        entreprise=entreprise,
        allowed_types=[StockMovement.MovementType.MANUAL_ENTRY],
        initial={"movement_type": StockMovement.MovementType.MANUAL_ENTRY},
    )
    response = _handle_stock_operation(
        request=request,
        entreprise=entreprise,
        form=form,
        operation="entry",
    )
    if response is not None:
        return response
    return render(
        request,
        "joatham_products/stock_movement_form.html",
        {
            **_build_stock_operation_context(
                form=form,
                page_title=_("Entree stock"),
                submit_label=_("Enregistrer l'entree"),
                help_text=_("Utilisez cette action pour enregistrer un reapprovisionnement ou une entree manuelle."),
            ),
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("stock.move")
@module_access_required("products")
def stock_exit_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = StockMovementForm(
        request.POST or None,
        entreprise=entreprise,
        allowed_types=[StockMovement.MovementType.MANUAL_EXIT],
        initial={"movement_type": StockMovement.MovementType.MANUAL_EXIT},
    )
    response = _handle_stock_operation(
        request=request,
        entreprise=entreprise,
        form=form,
        operation="exit",
    )
    if response is not None:
        return response
    return render(
        request,
        "joatham_products/stock_movement_form.html",
        {
            **_build_stock_operation_context(
                form=form,
                page_title=_("Sortie stock"),
                submit_label=_("Enregistrer la sortie"),
                help_text=_("Utilisez cette action pour enregistrer une sortie manuelle ou une perte constatee."),
            ),
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("stock.adjust")
@module_access_required("products")
def stock_adjustment_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = StockMovementForm(
        request.POST or None,
        entreprise=entreprise,
        allowed_types=[
            StockMovement.MovementType.ADJUSTMENT_POSITIVE,
            StockMovement.MovementType.ADJUSTMENT_NEGATIVE,
        ],
    )
    response = _handle_stock_operation(
        request=request,
        entreprise=entreprise,
        form=form,
        operation="adjustment",
    )
    if response is not None:
        return response
    return render(
        request,
        "joatham_products/stock_movement_form.html",
        {
            **_build_stock_operation_context(
                form=form,
                page_title=_("Ajustement stock"),
                submit_label=_("Enregistrer l'ajustement"),
                help_text=_("Utilisez cette action pour corriger un ecart de stock apres verification interne."),
            ),
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("stock.view")
@module_access_required("products")
def inventory_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    filters = _get_inventory_filters_from_request(request)
    sessions = get_inventory_sessions_for_entreprise(
        entreprise,
        status=filters["status"],
        date_debut=filters["date_debut"],
        date_fin=filters["date_fin"],
    )
    rows = [
        {
            "instance": session,
            "status_label": _build_inventory_status_label(session.status),
        }
        for session in sessions
    ]
    return render(
        request,
        "joatham_products/inventory_list.html",
        {
            "sessions": rows,
            "status_choices": [
                ("", _("Tous les statuts")),
                ("draft", _("Brouillon")),
                ("in_progress", _("En cours")),
                ("closed", _("Cloture")),
                ("validated", _("Valide")),
                ("cancelled", _("Annule")),
            ],
            **filters,
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("stock.inventory")
@module_access_required("products")
def inventory_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = InventorySessionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        session = create_inventory_session(
            entreprise=entreprise,
            name=form.cleaned_data["name"],
            comment=form.cleaned_data["comment"],
            utilisateur=request.user,
            include_active_products=True,
        )
        messages.success(request, _("La session d'inventaire a ete creee avec succes."))
        return redirect("inventory_detail", pk=session.id)

    return render(
        request,
        "joatham_products/inventory_form.html",
        {
            "form": form,
            "page_title": _("Nouvel inventaire physique"),
            "submit_label": _("Creer l'inventaire"),
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("stock.view")
@module_access_required("products")
def inventory_detail(request, pk):
    entreprise = get_user_entreprise_or_raise(request.user)
    session = get_inventory_session_for_entreprise(entreprise, pk)
    lines = get_inventory_lines_for_session(entreprise, session)
    summary = get_inventory_summary(entreprise, session)
    return render(
        request,
        "joatham_products/inventory_detail.html",
        {
            "session": session,
            "status_label": _build_inventory_status_label(session.status),
            "summary": summary,
            "lines": _build_inventory_lines_data(lines),
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("stock.inventory")
@module_access_required("products")
def inventory_count(request, pk):
    entreprise = get_user_entreprise_or_raise(request.user)
    session = get_inventory_session_for_entreprise(entreprise, pk)
    try:
        if session.status == session.Status.DRAFT:
            session = start_inventory_session(entreprise=entreprise, session_id=session.id)
    except InventoryOperationError as exc:
        messages.error(request, str(exc))
        return redirect("inventory_detail", pk=session.id)

    if session.status != session.Status.IN_PROGRESS:
        messages.error(request, _("Seules les sessions en cours peuvent etre comptees."))
        return redirect("inventory_detail", pk=session.id)

    lines = list(get_inventory_lines_for_session(entreprise, session))
    initial = [
        {
            "line_id": line.id,
            "counted_quantity": line.counted_quantity if line.counted_quantity is not None else "",
            "comment": line.comment,
        }
        for line in lines
    ]
    formset = InventoryCountFormSet(request.POST or None, initial=initial)

    if request.method == "POST" and formset.is_valid():
        try:
            for form in formset:
                record_inventory_count(
                    entreprise=entreprise,
                    session_id=session.id,
                    line_id=form.cleaned_data["line_id"],
                    counted_quantity=form.cleaned_data["counted_quantity"],
                    comment=form.cleaned_data["comment"],
                )
        except InventoryOperationError as exc:
            formset._non_form_errors = formset.error_class([str(exc)])
        else:
            messages.success(request, _("Les comptages ont ete enregistres avec succes."))
            return redirect("inventory_detail", pk=session.id)

    line_forms = []
    for form, line in zip(formset.forms, lines):
        line_forms.append({"form": form, "line": line})

    return render(
        request,
        "joatham_products/inventory_count.html",
        {
            "session": session,
            "status_label": _build_inventory_status_label(session.status),
            "formset": formset,
            "line_forms": line_forms,
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("stock.inventory")
@module_access_required("products")
def inventory_close(request, pk):
    if request.method != "POST":
        raise PermissionDenied("Cette action doit etre soumise par formulaire.")
    entreprise = get_user_entreprise_or_raise(request.user)
    try:
        close_inventory_session(entreprise=entreprise, session_id=pk)
    except InventoryOperationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("La session d'inventaire a ete cloturee."))
    return redirect("inventory_detail", pk=pk)


@permission_required("stock.inventory")
@module_access_required("products")
def inventory_validate(request, pk):
    if request.method != "POST":
        raise PermissionDenied("Cette action doit etre soumise par formulaire.")
    entreprise = get_user_entreprise_or_raise(request.user)
    try:
        validate_inventory_session(
            entreprise=entreprise,
            session_id=pk,
            utilisateur=request.user,
        )
    except (InventoryOperationError, StockOperationError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("L'inventaire a ete valide et les ajustements ont ete enregistres."))
    return redirect("inventory_detail", pk=pk)


@permission_required("stock.inventory")
@module_access_required("products")
def inventory_cancel(request, pk):
    if request.method != "POST":
        raise PermissionDenied("Cette action doit etre soumise par formulaire.")
    entreprise = get_user_entreprise_or_raise(request.user)
    try:
        cancel_inventory_session(entreprise=entreprise, session_id=pk)
    except InventoryOperationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("La session d'inventaire a ete annulee."))
    return redirect("inventory_detail", pk=pk)
