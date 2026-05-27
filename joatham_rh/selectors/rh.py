from datetime import timedelta

from django.db.models import Count, Q
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


def get_employes_by_entreprise(entreprise, *, active_only=False, statut=None, poste_id=None, search=None):
    queryset = (
        scope_queryset_to_entreprise(Employe.objects.select_related("poste"), entreprise)
        .order_by("nom", "prenom", "id")
    )
    if active_only:
        queryset = queryset.filter(actif=True)
    if statut:
        queryset = queryset.filter(statut=statut)
    if poste_id:
        queryset = queryset.filter(poste_id=poste_id)
    if search:
        queryset = queryset.filter(
            Q(matricule__icontains=search)
            | Q(nom__icontains=search)
            | Q(prenom__icontains=search)
        )
    return queryset


def get_employe_by_entreprise(entreprise, employe_id):
    return get_object_for_entreprise(
        Employe.objects.select_related("poste"),
        entreprise,
        id=employe_id,
    )


def get_presences_by_entreprise(entreprise, *, date_debut=None, date_fin=None, employe_id=None, statut=None):
    queryset = (
        scope_queryset_to_entreprise(Presence.objects.select_related("employe", "employe__poste"), entreprise)
        .order_by("-date", "employe__nom", "id")
    )
    if date_debut:
        queryset = queryset.filter(date__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(date__lte=date_fin)
    if employe_id:
        queryset = queryset.filter(employe_id=employe_id)
    if statut:
        queryset = queryset.filter(statut=statut)
    return queryset


def get_conges_by_entreprise(entreprise, *, statut=None, type_conge=None, date_debut=None, date_fin=None):
    queryset = (
        scope_queryset_to_entreprise(DemandeConge.objects.select_related("employe", "approuve_par"), entreprise)
        .order_by("-date_debut", "-id")
    )
    if statut:
        queryset = queryset.filter(statut=statut)
    if type_conge:
        queryset = queryset.filter(type_conge=type_conge)
    if date_debut:
        queryset = queryset.filter(date_fin__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(date_debut__lte=date_fin)
    return queryset


def get_conge_by_entreprise(entreprise, conge_id):
    return get_object_for_entreprise(
        DemandeConge.objects.select_related("employe", "approuve_par"),
        entreprise,
        id=conge_id,
    )


def get_documents_by_entreprise(entreprise, *, type_document=None, employe_id=None):
    queryset = (
        scope_queryset_to_entreprise(DocumentRH.objects.select_related("employe"), entreprise)
        .order_by("-created_at", "-id")
    )
    if type_document:
        queryset = queryset.filter(type_document=type_document)
    if employe_id:
        queryset = queryset.filter(employe_id=employe_id)
    return queryset


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
    presences = scope_queryset_to_entreprise(Presence.objects.all(), entreprise)
    presences_month = presences.filter(
        date__gte=month_start,
        date__lte=month_end,
    )
    conges = scope_queryset_to_entreprise(DemandeConge.objects.all(), entreprise)
    conges_month = conges.filter(date_debut__lte=month_end, date_fin__gte=month_start)
    documents = scope_queryset_to_entreprise(DocumentRH.objects.all(), entreprise)
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
        "presences_aujourdhui": presences.filter(date=as_of, statut=Presence.Statut.PRESENT).count(),
        "absences_mois": presences_month.filter(statut__in=[Presence.Statut.ABSENT, Presence.Statut.CONGE]).count(),
        "conges_mois": conges_month.filter(statut=DemandeConge.Statut.APPROUVE).count(),
        "conges_en_attente": conges.filter(statut=DemandeConge.Statut.EN_ATTENTE).count(),
        "conges_approuves": conges.filter(statut=DemandeConge.Statut.APPROUVE).count(),
        "documents_total": documents.count(),
        "recent_employes": list(
            scope_queryset_to_entreprise(
                Employe.objects.select_related("poste"),
                entreprise,
            ).order_by("-created_at", "-id")[:5]
        ),
        "recent_presences": list(
            scope_queryset_to_entreprise(
                Presence.objects.select_related("employe"),
                entreprise,
            ).order_by("-created_at", "-id")[:5]
        ),
        "recent_conges": list(
            scope_queryset_to_entreprise(
                DemandeConge.objects.select_related("employe"),
                entreprise,
            ).order_by("-created_at", "-id")[:5]
        ),
        "recent_documents": list(
            scope_queryset_to_entreprise(
                DocumentRH.objects.select_related("employe"),
                entreprise,
            ).order_by("-created_at", "-id")[:5]
        ),
        "repartition_postes": [
            {"poste": row["poste__nom"] or "Sans poste", "total": row["total"]}
            for row in repartition_postes
        ],
        "month_start": month_start,
        "month_end": month_end,
    }
