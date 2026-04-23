from django.contrib import messages
from django.shortcuts import redirect, render

from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.permissions import permission_required, require_permission, user_has_permission

from .forms import ProduitForm
from .selectors.products import (
    STOCK_FILTER_ALL,
    STOCK_FILTER_LOW,
    STOCK_FILTER_RUPTURE,
    get_product_by_entreprise,
    get_product_counts_by_entreprise,
)
from .services.products_service import create_product_for_entreprise, list_products_for_entreprise, update_product_for_entreprise


def _build_product_ui_permissions(user):
    return {
        "can_manage_products_ui": user_has_permission(user, "products.manage"),
    }


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
                "en_stock": "En stock",
                "stock_faible": "Stock faible",
                "rupture": "Rupture",
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
                {"value": STOCK_FILTER_ALL, "label": "Tous"},
                {"value": STOCK_FILTER_LOW, "label": "Stock faible"},
                {"value": STOCK_FILTER_RUPTURE, "label": "Rupture"},
            ],
            **counts,
            **_build_product_ui_permissions(request.user),
        },
    )


@permission_required("products.manage")
@module_access_required("products")
def product_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = ProduitForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        create_product_for_entreprise(
            entreprise=entreprise,
            utilisateur=request.user,
            **form.cleaned_data,
        )
        messages.success(request, "Le produit a été créé avec succès.")
        return redirect("product_list")

    return render(
        request,
        "joatham_products/product_form.html",
        {
            "form": form,
            "page_title": "Créer un produit",
            "submit_label": "Créer le produit",
        },
    )


@permission_required("products.view")
@module_access_required("products")
def product_update(request, product_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    produit = get_product_by_entreprise(entreprise, product_id)
    require_permission(request.user, "products.manage")
    form = ProduitForm(request.POST or None, instance=produit)

    if request.method == "POST" and form.is_valid():
        update_product_for_entreprise(
            entreprise=entreprise,
            product_id=produit.id,
            utilisateur=request.user,
            **form.cleaned_data,
        )
        messages.success(request, "Le produit a été mis à jour avec succès.")
        return redirect("product_list")

    return render(
        request,
        "joatham_products/product_form.html",
        {
            "form": form,
            "page_title": "Modifier un produit",
            "submit_label": "Enregistrer les modifications",
            "product": produit,
        },
    )
