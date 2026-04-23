from core.services.tenancy import get_object_for_entreprise, scope_queryset_to_entreprise
from joatham_users.models import Entreprise

from ..models import CompteComptable, EcritureComptable, ExerciceComptable, JournalComptable, LigneEcritureComptable


def get_entreprises_for_accounting_user(user):
    queryset = Entreprise.objects.order_by("nom")
    if user.is_superuser:
        return queryset
    entreprise = getattr(user, "entreprise", None)
    if entreprise is None:
        return queryset.none()
    return queryset.filter(pk=entreprise.pk)


def get_comptes_by_entreprise(entreprise, *, actif_only=False):
    queryset = scope_queryset_to_entreprise(CompteComptable.objects.all(), entreprise).order_by("numero")
    if actif_only:
        queryset = queryset.filter(actif=True)
    return queryset


def get_compte_by_entreprise(entreprise, compte_id):
    return get_object_for_entreprise(CompteComptable.objects.all(), entreprise, id=compte_id)


def get_journaux_by_entreprise(entreprise, *, actif_only=False):
    queryset = scope_queryset_to_entreprise(JournalComptable.objects.all(), entreprise).order_by("code")
    if actif_only:
        queryset = queryset.filter(actif=True)
    return queryset


def get_exercices_by_entreprise(entreprise):
    return scope_queryset_to_entreprise(ExerciceComptable.objects.all(), entreprise).order_by("-date_debut")


def get_ecritures_by_entreprise(entreprise, *, date_debut=None, date_fin=None, statut=EcritureComptable.Statut.VALIDE):
    queryset = scope_queryset_to_entreprise(
        EcritureComptable.objects.select_related("journal", "exercice", "entreprise"),
        entreprise,
    ).order_by("-date_piece", "-id")
    if statut:
        queryset = queryset.filter(statut=statut)
    if date_debut:
        queryset = queryset.filter(date_piece__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(date_piece__lte=date_fin)
    return queryset


def get_lignes_ecriture_by_entreprise(entreprise, *, date_debut=None, date_fin=None, statut=EcritureComptable.Statut.VALIDE):
    queryset = LigneEcritureComptable.objects.select_related("ecriture", "ecriture__journal", "compte").filter(
        ecriture__entreprise=entreprise,
    )
    if statut:
        queryset = queryset.filter(ecriture__statut=statut)
    if date_debut:
        queryset = queryset.filter(ecriture__date_piece__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(ecriture__date_piece__lte=date_fin)
    return queryset.order_by("compte__numero", "ecriture__date_piece", "ecriture_id", "id")


def get_lignes_ecriture_before_date_by_entreprise(entreprise, date_debut, *, statut=EcritureComptable.Statut.VALIDE):
    if not date_debut:
        return LigneEcritureComptable.objects.none()
    return (
        LigneEcritureComptable.objects.select_related("compte")
        .filter(
            ecriture__entreprise=entreprise,
            ecriture__statut=statut,
            ecriture__date_piece__lt=date_debut,
        )
        .order_by("compte__numero", "ecriture__date_piece", "ecriture_id", "id")
    )
