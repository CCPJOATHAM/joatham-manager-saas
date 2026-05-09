from django.db import transaction

from core.audit import record_audit_event
from core.services.quotas import assert_cashbox_quota_available
from core.services.tenancy import ensure_same_entreprise

from ..models import Caisse, SessionCaisse
from ..selectors.caisse import get_caisses_by_entreprise


def list_caisses_for_entreprise(entreprise):
    return get_caisses_by_entreprise(entreprise)


@transaction.atomic
def create_caisse(
    *,
    entreprise,
    nom,
    code,
    description="",
    devise="",
    est_active=True,
    utilisateur=None,
):
    if est_active:
        assert_cashbox_quota_available(entreprise)
    if Caisse.objects.filter(entreprise=entreprise, code=(code or "").strip()).exists():
        raise ValueError("Une caisse avec ce code existe deja dans votre entreprise.")

    caisse = Caisse.objects.create(
        entreprise=entreprise,
        nom=(nom or "").strip(),
        code=(code or "").strip(),
        description=(description or "").strip(),
        devise=(devise or getattr(entreprise, "devise", "") or "CDF").strip().upper(),
        est_active=est_active,
        cree_par=utilisateur,
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="caisse_created",
        module="caisse",
        objet_type="Caisse",
        objet_id=caisse.id,
        description=f"Caisse creee : {caisse.nom}.",
        metadata={"code": caisse.code, "devise": caisse.devise, "est_active": caisse.est_active},
    )
    return caisse


create_caisse_for_entreprise = create_caisse


@transaction.atomic
def update_caisse(
    *,
    entreprise,
    caisse,
    nom,
    code,
    description="",
    devise="",
    est_active=True,
    utilisateur=None,
):
    ensure_same_entreprise(caisse, entreprise)
    if est_active and not caisse.est_active:
        assert_cashbox_quota_available(entreprise)
    normalized_code = (code or "").strip()
    if Caisse.objects.filter(entreprise=entreprise, code=normalized_code).exclude(pk=caisse.pk).exists():
        raise ValueError("Une caisse avec ce code existe deja dans votre entreprise.")

    old_values = {
        "nom": caisse.nom,
        "code": caisse.code,
        "description": caisse.description,
        "devise": caisse.devise,
        "est_active": caisse.est_active,
    }
    caisse.nom = (nom or "").strip()
    caisse.code = normalized_code
    caisse.description = (description or "").strip()
    caisse.devise = (devise or getattr(entreprise, "devise", "") or "CDF").strip().upper()
    caisse.est_active = est_active
    caisse.save()
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="caisse_updated",
        module="caisse",
        objet_type="Caisse",
        objet_id=caisse.id,
        description=f"Caisse mise a jour : {caisse.nom}.",
        metadata={
            "before": old_values,
            "after": {
                "nom": caisse.nom,
                "code": caisse.code,
                "description": caisse.description,
                "devise": caisse.devise,
                "est_active": caisse.est_active,
            },
        },
    )
    return caisse


@transaction.atomic
def deactivate_caisse(*, entreprise, caisse, utilisateur=None):
    ensure_same_entreprise(caisse, entreprise)
    if caisse.sessions.filter(statut=SessionCaisse.Statut.OUVERTE).exists():
        raise ValueError("Impossible de desactiver une caisse avec une session ouverte.")
    if not caisse.est_active:
        return caisse

    caisse.est_active = False
    caisse.save(update_fields=["est_active", "date_modification"])
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="caisse_deactivated",
        module="caisse",
        objet_type="Caisse",
        objet_id=caisse.id,
        description=f"Caisse desactivee : {caisse.nom}.",
        metadata={"code": caisse.code},
    )
    return caisse
