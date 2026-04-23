from django.shortcuts import redirect, render

from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.permissions import permission_required

from .services.clients_service import (
    create_client_for_entreprise,
    delete_client,
    get_client_for_entreprise,
    list_clients_for_entreprise,
    update_client,
)


@permission_required("clients.view")
@module_access_required("clients")
def client_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    search = request.GET.get("q", "").strip()
    clients = list_clients_for_entreprise(entreprise, search=search or None)
    return render(
        request,
        "joatham_clients/client_list.html",
        {
            "clients": clients,
            "search": search,
            "client_count": clients.count(),
        },
    )


@permission_required("clients.manage")
@module_access_required("clients")
def add_client(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    if request.method == "POST":
        create_client_for_entreprise(
            entreprise=entreprise,
            nom=request.POST.get("nom", ""),
            telephone=request.POST.get("telephone", ""),
            email=request.POST.get("email", ""),
            utilisateur=request.user,
        )
        return redirect("client_list")

    return render(request, "joatham_clients/add_client.html")


@permission_required("clients.manage")
def delete_client(request, id):
    entreprise = get_user_entreprise_or_raise(request.user)
    client = get_client_for_entreprise(entreprise, id)
    delete_client(client)
    return redirect("client_list")


@permission_required("clients.manage")
def edit_client(request, id):
    entreprise = get_user_entreprise_or_raise(request.user)
    client = get_client_for_entreprise(entreprise, id)

    if request.method == "POST":
        update_client(
            client,
            nom=request.POST.get("nom", ""),
            telephone=request.POST.get("telephone", ""),
            email=request.POST.get("email", ""),
        )
        return redirect("client_list")

    return render(request, "joatham_clients/edit_client.html", {"client": client})
