from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from core.services.tenancy import get_object_for_entreprise, scope_queryset_to_entreprise

from ..models import DemandeConge, DocumentRH, Employe, Poste, Presence


def get_postes_by_entreprise(entreprise, *, active_only=False):
    queryset = scope_queryset_to_entreprise(Poste.objects.all(), entreprise).order_by("nom", "id")
    if active_only:
        queryset = queryset.filter(actif=True)
    return queryset


def get_poste_by_entreprise(entreprise, poste_id):
    return get_object_for_entreprise(Poste.objects.all(), entreprise, id=poste_id)


def get_employes_by_entreprise(entreprise, *, active_only=False):
    queryset = (
        scope_queryset_to_entreprise(Employe.objects.select_related("poste"), entreprise)
        .order_by("nom", "prenom", "id")
    )
    if active_only:
        queryset = queryset.filter(actif=True)
    return queryset


def get_employe_by_entreprise(entreprise, employe_id):
    return get_object_for_entreprise(
        Employe.objects.select_related("poste"),
        entreprise,
        id=employe_id,
    )


def get_presences_by_entreprise(entreprise):
    return (
        scope_queryset_to_entreprise(Presence.objects.select_related("employe", "employe__poste"), entreprise)
        .order_by("-date", "employe__nom", "id")
    )


def get_conges_by_entreprise(entreprise):
    return (
        scope_queryset_to_entreprise(DemandeConge.objects.select_related("employe", "approuve_par"), entreprise)
        .order_by("-date_debut", "-id")
    )


def get_conge_by_entreprise(entreprise, conge_id):
    return get_object_for_entreprise(
        DemandeConge.objects.select_related("employe", "approuve_par"),
        entreprise,
        id=conge_id,
    )


def get_documents_by_entreprise(entreprise):
    return (
        scope_queryset_to_entreprise(DocumentRH.objects.select_related("employe"), entreprise)
        .order_by("-created_at", "-id")
    )


def get_document_by_entreprise(entreprise, document_id):
    return get_object_for_entreprise(
        DocumentRH.objects.select_related("employe"),
        entreprise,
        id=document_id,
    )


def get_rh_report_snapshot(entreprise, *, as_of=None):
    as_of = as_of or timezone.localdate()
    month_start = as_of.replace(day=1)
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    month_end = next_month - timedelta(days=1)

    employes = scope_queryset_to_entreprise(Employe.objects.all(), entreprise)
    presences_month = scope_queryset_to_entreprise(Presence.objects.all(), entreprise).filter(
        date__gte=month_start,
        date__lte=month_end,
    )
    conges = scope_queryset_to_entreprise(DemandeConge.objects.all(), entreprise)
    conges_month = conges.filter(date_debut__lte=month_end, date_fin__gte=month_start)
    repartition_postes = (
        employes.values("poste__nom")
        .annotate(total=Count("id"))
        .order_by("poste__nom")
    )

    return {
        "total_employes": employes.count(),
        "employes_actifs": employes.filter(statut=Employe.Statut.ACTIF, actif=True).count(),
        "employes_suspendus": employes.filter(statut=Employe.Statut.SUSPENDU).count(),
        "employes_sortis": employes.filter(statut=Employe.Statut.SORTI).count(),
        "presences_mois": presences_month.filter(statut=Presence.Statut.PRESENT).count(),
        "absences_mois": presences_month.filter(statut__in=[Presence.Statut.ABSENT, Presence.Statut.CONGE]).count(),
        "conges_mois": conges_month.filter(statut=DemandeConge.Statut.APPROUVE).count(),
        "conges_en_attente": conges.filter(statut=DemandeConge.Statut.EN_ATTENTE).count(),
        "conges_approuves": conges.filter(statut=DemandeConge.Statut.APPROUVE).count(),
        "repartition_postes": [
            {"poste": row["poste__nom"] or "Sans poste", "total": row["total"]}
            for row in repartition_postes
        ],
        "month_start": month_start,
        "month_end": month_end,
    }
