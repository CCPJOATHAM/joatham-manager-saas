from core.services.tenancy import get_object_for_entreprise
from core.audit import record_audit_event

from ..models import Client
from ..selectors.clients import get_clients_by_entreprise


def list_clients_for_entreprise(entreprise, *, search=None):
    return get_clients_by_entreprise(entreprise, search=search)


def get_client_for_entreprise(entreprise, client_id):
    return get_object_for_entreprise(Client.objects.all(), entreprise, id=client_id)


def create_client_for_entreprise(*, entreprise, nom, telephone, email, utilisateur=None):
    client = Client.objects.create(
        nom=(nom or "").strip(),
        telephone=(telephone or "").strip(),
        email=(email or "").strip(),
        entreprise=entreprise,
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="client_cree",
        module="clients",
        objet_type="Client",
        objet_id=client.id,
        description=f"Client cree: {client.nom}.",
        metadata={"email": client.email, "telephone": client.telephone},
    )
    return client


def update_client(client, *, nom, telephone, email):
    client.nom = (nom or "").strip()
    client.telephone = (telephone or "").strip()
    client.email = (email or "").strip()
    client.save()
    return client


def delete_client(client):
    client.delete()
