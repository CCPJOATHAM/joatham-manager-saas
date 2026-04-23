from decimal import Decimal

from joatham_billing.services.facturation import create_facture, register_payment
from joatham_clients.models import Client
from joatham_depenses.models import Depense
from joatham_users.models import Entreprise, User


def create_entreprise(name="Entreprise Compta"):
    return Entreprise.objects.create(nom=name)


def create_user(username, role, entreprise):
    return User.objects.create_user(username=username, password="testpass123", role=role, entreprise=entreprise)


def create_client(entreprise, nom="Client Compta"):
    return Client.objects.create(
        nom=nom,
        telephone="+243000000000",
        email=f"{nom.lower().replace(' ', '')}@example.com",
        entreprise=entreprise,
    )


def create_facture_and_payment(entreprise, gestionnaire, comptable):
    client = create_client(entreprise)
    facture = create_facture(
        entreprise=entreprise,
        user=gestionnaire,
        client_id=client.id,
        tva=16,
        lignes=[{"designation": "Prestation", "quantite": 1, "prix": Decimal("100")}],
    )
    paiement = register_payment(
        facture=facture,
        montant=Decimal("50"),
        mode="especes",
        user=comptable,
        note="Acompte",
    )
    return facture, paiement


def create_depense(entreprise, description="Achat papier", montant=Decimal("25")):
    return Depense.objects.create(description=description, montant=montant, entreprise=entreprise)
