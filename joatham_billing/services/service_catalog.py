from core.audit import record_audit_event

from ..models import Service
from ..selectors.billing import get_service_by_entreprise, get_services_by_entreprise


def list_services_for_entreprise(entreprise):
    return get_services_by_entreprise(entreprise)


def create_service_for_entreprise(*, entreprise, nom, prix, actif=True, utilisateur=None):
    service = Service.objects.create(
        entreprise=entreprise,
        nom=(nom or "").strip(),
        prix=prix,
        actif=actif,
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="service_cree",
        module="services",
        objet_type="Service",
        objet_id=service.id,
        description=f"Service créé : {service.nom}.",
        metadata={"prix": str(service.prix), "actif": service.actif},
    )
    return service


def update_service_for_entreprise(*, entreprise, service_id, nom, prix, actif=True, utilisateur=None):
    service = get_service_by_entreprise(entreprise, service_id)
    previous_active = service.actif
    service.nom = (nom or "").strip()
    service.prix = prix
    service.actif = actif
    service.save()
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="service_modifie",
        module="services",
        objet_type="Service",
        objet_id=service.id,
        description=f"Service modifié : {service.nom}.",
        metadata={"prix": str(service.prix), "actif": service.actif},
    )
    if previous_active != service.actif:
        record_audit_event(
            entreprise=entreprise,
            utilisateur=utilisateur,
            action="service_statut_modifie",
            module="services",
            objet_type="Service",
            objet_id=service.id,
            description=f"Statut du service modifié : {service.nom}.",
            metadata={"actif": service.actif},
        )
    return service


def toggle_service_active(*, entreprise, service_id, utilisateur=None):
    service = get_service_by_entreprise(entreprise, service_id)
    service.actif = not service.actif
    service.save(update_fields=["actif"])
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="service_statut_modifie",
        module="services",
        objet_type="Service",
        objet_id=service.id,
        description=f"Statut du service modifié : {service.nom}.",
        metadata={"actif": service.actif},
    )
    return service
