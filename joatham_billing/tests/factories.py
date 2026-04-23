from decimal import Decimal

from joatham_billing.models import Facture
from joatham_billing.services.facturation import create_facture
from joatham_clients.models import Client
from joatham_users.models import Entreprise, User


def create_entreprise(name="CCP JOATHAM"):
    return Entreprise.objects.create(nom=name)


def create_user(username, role, entreprise):
    return User.objects.create_user(username=username, password="testpass123", role=role, entreprise=entreprise)


def create_client(entreprise, nom="Client Test"):
    return Client.objects.create(
        nom=nom,
        telephone="+243000000000",
        email=f"{nom.lower().replace(' ', '')}@example.com",
        entreprise=entreprise,
    )


def create_facture_sample(entreprise, user, client=None, montant=Decimal("100")):
    client = client or create_client(entreprise)
    return create_facture(
        entreprise=entreprise,
        user=user,
        client_id=client.id,
        tva=Decimal("16"),
        lignes=[
            {
                "designation": "Service test",
                "quantite": 1,
                "prix": montant,
            }
        ],
    )
