"""Reversible closure and a deliberately conservative, fail-closed purge policy.

No business record is eligible for cascade deletion in this first policy. A legal
retention/archival design must be reviewed before expanding the allowlist.
"""
from collections import defaultdict, deque
from datetime import timedelta
import hashlib
import json

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.audit import record_audit_event
from core.models import ActivityLog, CompanyDeletionRequest
from joatham_users.models import Entreprise, User, UserActiveSession
from joatham_users.permissions import get_user_role, ROLE_SUPER_ADMIN

# Global plans, business entities, documents and unknown future models are NEVER
# eligible. Auth through rows remove memberships, not shared groups/permissions.
PURGE_ALLOWLIST = frozenset({
    "joatham_users.entreprise", "joatham_users.user", "joatham_users.useractivesession",
    "joatham_users.abonnemententreprise", "joatham_users.user_groups", "joatham_users.user_user_permissions",
})
RETAINED_MODELS = {"core.activitylog", "core.companydeletionrequest"}
CATEGORY_LABELS = {
    "joatham_users": _("Entreprise, comptes et accès"),
    "joatham_clients": _("Clients"), "joatham_billing": _("Factures et documents commerciaux"),
    "joatham_payments": _("Paiements"), "joatham_depenses": _("Dépenses"),
    "joatham_caisse": _("Caisse"), "joatham_products": _("Produits et stock"),
    "joatham_services": _("Services"), "joatham_comptabilite": _("Comptabilité"),
    "joatham_rh": _("Ressources humaines"), "joatham_apprenants": _("Apprenants"),
    "joatham_messages": _("Messagerie"), "core": _("Abonnements et audit"),
}


class DeletionWorkflowError(ValueError):
    pass


def require_super_admin(actor):
    if actor is None or not getattr(actor, "pk", None):
        raise PermissionDenied(_("Action réservée au super-administrateur actif."))
    actor = User.objects.get(pk=actor.pk)
    if not actor.is_active or get_user_role(actor) != ROLE_SUPER_ADMIN:
        raise PermissionDenied(_("Action réservée au super-administrateur actif."))
    return actor


def is_deletion_pending(company_id):
    return CompanyDeletionRequest.objects.filter(entreprise_id=company_id, status=CompanyDeletionRequest.Status.PENDING).exists()


def _confirm(company, name, reason):
    if name != company.nom:
        raise DeletionWorkflowError(_("Le nom saisi ne correspond pas exactement au nom de l'entreprise."))
    if not (reason or "").strip() or len(reason) > 2000:
        raise DeletionWorkflowError(_("Un motif de 1 à 2 000 caractères est obligatoire."))


def _audit(company, actor, action, description, reason, **metadata):
    return record_audit_event(
        entreprise=company, utilisateur=actor, action=action, module="super_admin",
        objet_type="Entreprise", objet_id=company.pk,
        description=description, metadata={"reason": reason, "company_id": company.pk, "company_name": company.nom, "actor_id": actor.pk, "actor_username": actor.username, **metadata}, fail_silently=False,
    )


def _revoke_sessions(company):
    records = UserActiveSession.objects.filter(user__entreprise=company)
    Session.objects.filter(session_key__in=records.values("session_key")).delete()
    records.delete()


@transaction.atomic
def schedule_deletion(*, company_id, actor, confirmation_name, reason):
    actor = require_super_admin(actor)
    company = Entreprise.objects.select_for_update().get(pk=company_id)
    _confirm(company, confirmation_name, reason)
    if company.user_set.filter(Q(role=ROLE_SUPER_ADMIN) | Q(is_superuser=True)).exists():
        raise DeletionWorkflowError(_("Cette entreprise possède un compte privilégié de plateforme. Une vérification est nécessaire."))
    days = settings.JOATHAM_COMPANY_DELETION_GRACE_DAYS
    if type(days) is not int or days < 1:
        raise DeletionWorkflowError(_("Le délai de restauration doit être un nombre positif de jours."))
    request = CompanyDeletionRequest.objects.select_for_update().filter(entreprise=company).first()
    if request and request.status == CompanyDeletionRequest.Status.PENDING:
        raise DeletionWorkflowError(_("Une suppression est déjà programmée. Le délai initial est conservé."))
    scope, external_references = collect_company_scope(company)
    now = timezone.now()
    values = dict(
        company_id_snapshot=company.pk, company_name_snapshot=company.nom,
        status=CompanyDeletionRequest.Status.PENDING, reason=reason.strip(), requested_by=actor,
        requested_at=now, recovery_until=now + timedelta(days=days), company_was_active=company.is_active,
        cancelled_by=None, cancelled_at=None, cancellation_reason="",
    )
    request, created = CompanyDeletionRequest.objects.update_or_create(entreprise=company, defaults=values)
    company.is_active = False
    company.save(update_fields=["is_active"])
    # Individual activation flags and subscription dates are not rewritten.
    _revoke_sessions(company)
    _audit(company, actor, "company_deletion_scheduled", "Company deletion scheduled.", reason.strip(),
           deletion_request_id=request.pk, recovery_until=request.recovery_until.isoformat(), grace_days=days,
           counts={model._meta.label_lower: len(ids) for model, ids in scope.items()})
    return request


@transaction.atomic
def cancel_deletion(*, company_id, actor, confirmation_name, reason):
    actor = require_super_admin(actor)
    company = Entreprise.objects.select_for_update().get(pk=company_id)
    _confirm(company, confirmation_name, reason)
    request = CompanyDeletionRequest.objects.select_for_update().filter(entreprise=company).first()
    if not request or request.status != CompanyDeletionRequest.Status.PENDING:
        raise DeletionWorkflowError(_("Aucune suppression en attente pour cette entreprise."))
    company.is_active = request.company_was_active
    company.save(update_fields=["is_active"])
    request.status = CompanyDeletionRequest.Status.CANCELLED
    request.cancelled_by, request.cancelled_at, request.cancellation_reason = actor, timezone.now(), reason.strip()
    request.save(update_fields=["status", "cancelled_by", "cancelled_at", "cancellation_reason", "updated_at"])
    _audit(company, actor, "company_deletion_cancelled", "Company deletion cancelled.", reason.strip(), deletion_request_id=request.pk)
    return request


def collect_company_scope(company):
    """Read-only reverse-relation closure, bounded and tenant-checked.

    Follow incoming FKs, not outgoing references to global plans or other tenants.
    Unknown models and cross-tenant references prevent purge rather than widening it.
    """
    limit = settings.JOATHAM_COMPANY_EXPORT_MAX_ROWS
    if type(limit) is not int or limit < 1:
        raise DeletionWorkflowError(_("La limite d'export doit être un entier positif."))
    scope = {Entreprise: {company.pk}}
    queue = deque([(Entreprise, {company.pk})])
    external = defaultdict(int)
    total = 1
    while queue:
        parent, ids = queue.popleft()
        for relation in parent._meta.get_fields(include_hidden=True):
            if not (relation.auto_created and not relation.concrete and (relation.one_to_many or relation.one_to_one)):
                continue
            model, field = relation.related_model, relation.field
            rows = model._base_manager.filter(**{f"{field.attname}__in": ids})
            tenant_field = next((f for f in model._meta.local_fields if f.name == "entreprise" and f.is_relation), None)
            if tenant_field:
                if rows.exclude(entreprise_id=company.pk).exists():
                    external[model._meta.label_lower] = 1  # Never expose external record ids or contents.
                rows = rows.filter(entreprise_id=company.pk)
            known = scope.get(model, set())
            if known:
                rows = rows.exclude(pk__in=known)
            found = set(rows.values_list("pk", flat=True)[:max(1, limit - total + 1)])
            if not found:
                continue
            total += len(found)
            if total > limit:
                raise DeletionWorkflowError(_("Le volume dépasse la limite de cet export. Un export administratif dédié est nécessaire."))
            scope.setdefault(model, set()).update(found)
            queue.append((model, found))
    return scope, dict(external)


def deletion_inventory(company):
    scope, external = collect_company_scope(company)
    categories = defaultdict(int)
    for model, ids in scope.items():
        categories[model._meta.app_label] += len(ids)
    return [{"label": CATEGORY_LABELS.get(app, _("Autres données")), "count": count} for app, count in sorted(categories.items())]


def _sensitive(name):
    return any(part in name.lower() for part in ("password", "token", "secret", "session_key", "api_key", "apikey", "authorization", "credential", "private_key")) or name in {"raw_provider_payload", "checkout_url", "provider_checkout_id"}


def _sanitize(value):
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items() if not _sensitive(k)}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


@transaction.atomic
def export_company(*, company_id, actor, confirmation_name, reason):
    actor = require_super_admin(actor)
    company = Entreprise.objects.select_for_update().get(pk=company_id)
    _confirm(company, confirmation_name, reason)
    scope, external = collect_company_scope(company)
    if external:
        raise DeletionWorkflowError(_("L'export est bloqué par une relation entre entreprises. Une vérification administrative est nécessaire."))
    data = {}
    for model, ids in sorted(scope.items(), key=lambda item: item[0]._meta.label_lower):
        if model._meta.auto_created or model is UserActiveSession or not (model._meta.app_label == "core" or model._meta.app_label.startswith("joatham_")):
            continue
        fields = [f for f in model._meta.concrete_fields if not _sensitive(f.name)]
        records = []
        for row in model._base_manager.filter(pk__in=ids).order_by("pk").values(*[f.attname for f in fields]):
            # Do not disclose foreign tenant identifiers via inconsistent FK links.
            for field in fields:
                if field.is_relation and row[field.attname] is not None and row[field.attname] not in scope.get(field.related_model, set()):
                    target = field.related_model
                    global_plan = target._meta.label_lower == "joatham_users.abonnement"
                    platform_actor = target is User and User.objects.filter(pk=row[field.attname], entreprise__isnull=True, role=ROLE_SUPER_ADMIN).exists()
                    if not (global_plan or platform_actor):
                        raise DeletionWorkflowError(_("L'export est bloqué par une relation entre entreprises. Une vérification administrative est nécessaire."))
                    row.pop(field.attname, None)
            records.append(_sanitize(row))
        data[model._meta.label_lower] = records
    payload = {"format": "joatham-company-structured-v1", "company_id": company.pk,
               "generated_at": timezone.now(), "binary_files_included": False,
               "external_references_withheld": bool(external), "data": data}
    content = json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False).encode("utf-8")
    _audit(company, actor, "company_deletion_exported", "Company structured export created.", reason.strip())
    return content


def build_purge_plan(company):
    scope, external = collect_company_scope(company)
    request = CompanyDeletionRequest.objects.filter(entreprise=company).first()
    blocked = {model._meta.label_lower: len(ids) for model, ids in scope.items()
               if model._meta.label_lower not in PURGE_ALLOWLIST | RETAINED_MODELS}
    files = []
    for model, ids in scope.items():
        for field in model._meta.concrete_fields:
            if field.get_internal_type() in {"FileField", "ImageField"} and model._base_manager.filter(pk__in=ids).exclude(**{field.name: ""}).exclude(**{f"{field.name}__isnull": True}).exists():
                files.append(f"{model._meta.label_lower}.{field.name}")
    privileged = company.user_set.filter(Q(role=ROLE_SUPER_ADMIN) | Q(is_superuser=True)).exists()
    plan = {"company_id": company.pk, "company_name": company.nom,
            "request_id": request.pk if request else None, "status": request.status if request else None,
            "recovery_until": request.recovery_until.isoformat() if request else None,
            "requested_at": request.requested_at.isoformat() if request else None,
            "counts": {m._meta.label_lower: len(ids) for m, ids in scope.items()},
            "retention_blockers": blocked, "external_reference_blockers": external,
            "file_blockers": sorted(files), "privileged_account_blocker": privileged,
            "recovery_window_expired": bool(request and request.status == "pending" and timezone.now() >= request.recovery_until),
            "purge_permitted": False, "policy_blocker": "retention_rules_not_approved"}
    fingerprint = {**plan, "cohort": {m._meta.label_lower: sorted(ids) for m, ids in scope.items()}}
    # Eligibility can change with time; it is checked again inside execute.
    fingerprint.pop("recovery_window_expired")
    plan["plan_hash"] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    return plan, scope


def purge_company(*, company_id, actor, confirmation_name, reason, **confirmation):
    """Intentionally no deletion implementation until retention policy is approved.

    A flag or operator-supplied approval string cannot unlock irreversible work.
    Keep the command/service contract explicit, and test this fail-closed gate.
    """
    actor = require_super_admin(actor)
    company = Entreprise.objects.get(pk=company_id)
    _confirm(company, confirmation_name, reason)
    _audit(company, actor, "company_deletion_purge_blocked", "Company irreversible purge blocked.", reason.strip(), policy_gate="retention_rules_not_approved")
    raise DeletionWorkflowError(_("La purge irréversible est bloquée tant que les règles de conservation ne sont pas validées et qu'une évolution distincte n'est pas approuvée."))
