from django.contrib.auth import get_user_model
from django.db import transaction

from core.audit import record_audit_event
from core.services.subscription import get_or_create_default_trial_plan, start_trial_for_entreprise
from joatham_users.models import Entreprise
from joatham_users.permissions import ROLE_PROPRIETAIRE


User = get_user_model()


def _split_full_name(full_name):
    full_name = (full_name or "").strip()
    if not full_name:
        return "", ""
    parts = full_name.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


@transaction.atomic
def register_entreprise_owner(*, company_name, raison_sociale, owner_full_name, email, telephone, pays, devise, password):
    normalized_email = (email or "").strip().lower()
    if User.objects.filter(email__iexact=normalized_email).exists() or User.objects.filter(username__iexact=normalized_email).exists():
        raise ValueError("Un compte existe deja avec cet email. Veuillez vous connecter.")

    entreprise = Entreprise.objects.create(
        nom=(company_name or "").strip(),
        raison_sociale=(raison_sociale or "").strip(),
        email=normalized_email,
        telephone=(telephone or "").strip(),
        pays=(pays or "").strip(),
        devise=(devise or "CDF").strip().upper(),
    )

    first_name, last_name = _split_full_name(owner_full_name)
    user = User.objects.create_user(
        username=normalized_email,
        email=normalized_email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        role=ROLE_PROPRIETAIRE,
        email_verified=False,
        entreprise=entreprise,
    )

    record_audit_event(
        entreprise=entreprise,
        utilisateur=user,
        action="entreprise_creee",
        module="onboarding",
        objet_type="Entreprise",
        objet_id=entreprise.id,
        description=f"Entreprise creee depuis le parcours SaaS: {entreprise.nom}.",
        metadata={"email": normalized_email, "pays": entreprise.pays, "devise": entreprise.devise},
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=user,
        action="utilisateur_cree",
        module="onboarding",
        objet_type="User",
        objet_id=user.id,
        description=f"Compte proprietaire cree pour {normalized_email}.",
        metadata={"role": user.role},
    )

    trial_plan = get_or_create_default_trial_plan()
    start_trial_for_entreprise(entreprise=entreprise, plan=trial_plan, utilisateur=user)
    return user
