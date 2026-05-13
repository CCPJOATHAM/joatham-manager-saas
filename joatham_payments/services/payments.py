from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.utils import timezone

from core.audit import record_audit_event
from joatham_billing.exceptions import FacturationError
from joatham_billing.models import Facture, PaiementFacture
from joatham_billing.services.facturation import register_payment
from joatham_caisse.models import Caisse, MouvementCaisse, SessionCaisse
from joatham_caisse.services.mouvements import record_mouvement
from joatham_depenses.models import Depense
from joatham_users.permissions import user_has_permission

from ..models import PaymentTransaction


class PaymentOperationError(ValueError):
    pass


def _normalize_amount(value):
    try:
        amount = Decimal(str(value or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaymentOperationError("Le montant du paiement est invalide.") from exc
    if amount <= Decimal("0"):
        raise PaymentOperationError("Le montant du paiement doit etre strictement positif.")
    return amount


def _select_for_update_self(queryset):
    if getattr(connection.features, "has_select_for_update_of", False):
        return queryset.select_for_update(of=("self",))
    return queryset.select_for_update()


def _ensure_same_entreprise(instance, entreprise, label):
    if instance is not None and getattr(instance, "entreprise_id", None) != getattr(entreprise, "id", None):
        raise PaymentOperationError(f"{label} introuvable pour cette entreprise.")
    return instance


def _resolve_instance(model, value, entreprise, label, *, queryset=None):
    if value is None or value == "":
        return None
    if isinstance(value, model):
        return _ensure_same_entreprise(value, entreprise, label)
    qs = queryset or model.objects.all()
    instance = qs.filter(id=value).first()
    if instance is None:
        raise PaymentOperationError(f"{label} introuvable.")
    return _ensure_same_entreprise(instance, entreprise, label)


def _resolve_session(value, entreprise, caisse=None):
    session = _resolve_instance(
        SessionCaisse,
        value,
        entreprise,
        "Session caisse",
        queryset=SessionCaisse.objects.select_related("caisse", "entreprise"),
    )
    if session is None:
        return None
    if caisse is not None and session.caisse_id != caisse.id:
        raise PaymentOperationError("La session selectionnee n'appartient pas a cette caisse.")
    if session.statut != SessionCaisse.Statut.OUVERTE:
        raise PaymentOperationError("La session de caisse doit etre ouverte.")
    return session


def _billing_mode_for_method(method):
    mode = PaiementFacture.ModePaiement
    return {
        PaymentTransaction.Method.CASH: mode.ESPECES,
        PaymentTransaction.Method.BANK_TRANSFER: mode.VIREMENT,
        PaymentTransaction.Method.MPESA: getattr(mode, "MPESA", mode.MOBILE_MONEY),
        PaymentTransaction.Method.ORANGE_MONEY: getattr(mode, "ORANGE_MONEY", mode.MOBILE_MONEY),
        PaymentTransaction.Method.AIRTEL_MONEY: getattr(mode, "AIRTEL_MONEY", mode.MOBILE_MONEY),
        PaymentTransaction.Method.AFRIMONEY: getattr(mode, "AFRIMONEY", mode.MOBILE_MONEY),
        PaymentTransaction.Method.CARD: getattr(mode, "CARTE", mode.AUTRE),
        PaymentTransaction.Method.OTHER: mode.AUTRE,
    }.get(method, mode.AUTRE)


def _cash_movement_type_for_transaction(transaction_obj):
    if transaction_obj.transaction_type == PaymentTransaction.TransactionType.ENCAISSEMENT:
        return MouvementCaisse.TypeMouvement.ENTREE
    if transaction_obj.transaction_type in {
        PaymentTransaction.TransactionType.DECAISSEMENT,
        PaymentTransaction.TransactionType.REMBOURSEMENT,
    }:
        return MouvementCaisse.TypeMouvement.SORTIE
    return MouvementCaisse.TypeMouvement.AJUSTEMENT


def _build_payment_note(transaction_obj):
    details = []
    if transaction_obj.is_mobile_money:
        details.append(transaction_obj.get_method_display())
        if transaction_obj.phone_number:
            details.append(f"telephone {transaction_obj.phone_number}")
    if transaction_obj.note:
        details.append(transaction_obj.note)
    return " - ".join(details)


def _link_invoice_payment(transaction_obj, utilisateur):
    if transaction_obj.paiement_facture_id:
        return transaction_obj
    if transaction_obj.transaction_type != PaymentTransaction.TransactionType.ENCAISSEMENT:
        raise PaymentOperationError("Seuls les encaissements peuvent solder une facture.")

    facture = Facture.objects.select_for_update().filter(id=transaction_obj.facture_id).first()
    if facture is None or facture.entreprise_id != transaction_obj.entreprise_id:
        raise PaymentOperationError("Facture introuvable.")
    if transaction_obj.amount > facture.reste_a_payer:
        raise PaymentOperationError("Le paiement ne peut pas etre superieur au reste a payer.")

    caisse = transaction_obj.caisse if transaction_obj.method == PaymentTransaction.Method.CASH else None
    try:
        paiement = register_payment(
            facture=facture,
            montant=transaction_obj.amount,
            mode=_billing_mode_for_method(transaction_obj.method),
            reference=transaction_obj.reference,
            note=_build_payment_note(transaction_obj),
            caisse=caisse,
            user=utilisateur,
        )
    except FacturationError as exc:
        raise PaymentOperationError(str(exc)) from exc

    movement = None
    if caisse is not None:
        movement = (
            MouvementCaisse.objects.filter(
                entreprise=transaction_obj.entreprise,
                source_app="joatham_billing",
                source_model="PaiementFacture",
                source_id=paiement.id,
            )
            .order_by("-id")
            .first()
        )
        if movement is not None and movement.moyen_paiement != transaction_obj.method:
            movement.moyen_paiement = transaction_obj.method
            movement.save(update_fields=["moyen_paiement", "date_modification"])

    transaction_obj.facture = facture
    transaction_obj.paiement_facture = paiement
    transaction_obj.caisse = paiement.caisse
    transaction_obj.session_caisse = paiement.session_caisse
    transaction_obj.mouvement_caisse = movement
    transaction_obj.save(
        update_fields=["facture", "paiement_facture", "caisse", "session_caisse", "mouvement_caisse", "updated_at"]
    )
    return transaction_obj


def _create_cash_movement(transaction_obj, utilisateur):
    if transaction_obj.mouvement_caisse_id:
        return transaction_obj
    if transaction_obj.method != PaymentTransaction.Method.CASH:
        return transaction_obj
    if not transaction_obj.caisse_id:
        return transaction_obj
    if not transaction_obj.session_caisse_id:
        transaction_obj.session_caisse = (
            SessionCaisse.objects.filter(
                entreprise=transaction_obj.entreprise,
                caisse=transaction_obj.caisse,
                statut=SessionCaisse.Statut.OUVERTE,
            )
            .order_by("-date_ouverture", "-id")
            .first()
        )
        if transaction_obj.session_caisse is None:
            raise PaymentOperationError("Aucune session de caisse ouverte pour ce paiement cash.")

    movement = record_mouvement(
        entreprise=transaction_obj.entreprise,
        caisse=transaction_obj.caisse,
        session=transaction_obj.session_caisse,
        type_mouvement=_cash_movement_type_for_transaction(transaction_obj),
        montant=transaction_obj.amount,
        libelle=f"Paiement {transaction_obj.get_transaction_type_display()}",
        reference=transaction_obj.reference,
        commentaire=transaction_obj.note,
        source_app="joatham_payments",
        source_model="PaymentTransaction",
        source_id=transaction_obj.id,
        utilisateur=utilisateur,
        moyen_paiement=transaction_obj.method,
    )
    transaction_obj.mouvement_caisse = movement
    transaction_obj.save(update_fields=["session_caisse", "mouvement_caisse", "updated_at"])
    return transaction_obj


def _audit_payment(transaction_obj, *, utilisateur, action, description, extra_metadata=None):
    record_audit_event(
        entreprise=transaction_obj.entreprise,
        utilisateur=utilisateur,
        action=action,
        module="payments",
        objet_type="PaymentTransaction",
        objet_id=transaction_obj.id,
        description=description,
        metadata={
            "transaction_type": transaction_obj.transaction_type,
            "method": transaction_obj.method,
            "status": transaction_obj.status,
            "amount": str(transaction_obj.amount),
            "currency": transaction_obj.currency,
            "reference": transaction_obj.reference,
            "facture_id": transaction_obj.facture_id,
            "depense_id": transaction_obj.depense_id,
            "caisse_id": transaction_obj.caisse_id,
            **(extra_metadata or {}),
        },
    )


@transaction.atomic
def create_payment_transaction(
    *,
    entreprise,
    transaction_type,
    method,
    amount,
    utilisateur,
    currency="",
    reference="",
    phone_number="",
    mobile_operator="",
    status=PaymentTransaction.Status.EN_ATTENTE,
    transaction_date=None,
    facture=None,
    depense=None,
    caisse=None,
    session_caisse=None,
    note="",
    attachment=None,
):
    if not user_has_permission(utilisateur, "payments.create"):
        raise PermissionDenied("Vous n'avez pas les droits pour enregistrer un paiement.")

    transaction_type = transaction_type or PaymentTransaction.TransactionType.ENCAISSEMENT
    method = method or PaymentTransaction.Method.CASH
    if transaction_type not in dict(PaymentTransaction.TransactionType.choices):
        raise PaymentOperationError("Le type de paiement est invalide.")
    if method not in dict(PaymentTransaction.Method.choices):
        raise PaymentOperationError("Le moyen de paiement est invalide.")

    desired_status = status or PaymentTransaction.Status.EN_ATTENTE
    if desired_status not in {PaymentTransaction.Status.EN_ATTENTE, PaymentTransaction.Status.CONFIRME}:
        raise PaymentOperationError("Un nouveau paiement doit etre en attente ou confirme.")
    if desired_status == PaymentTransaction.Status.CONFIRME and not user_has_permission(utilisateur, "payments.validate"):
        raise PermissionDenied("Vous n'avez pas les droits pour confirmer un paiement.")

    facture_obj = _resolve_instance(
        Facture,
        facture,
        entreprise,
        "Facture",
        queryset=Facture.objects.select_related("entreprise"),
    )
    depense_obj = _resolve_instance(
        Depense,
        depense,
        entreprise,
        "Depense",
        queryset=Depense.objects.select_related("entreprise"),
    )
    caisse_obj = _resolve_instance(
        Caisse,
        caisse,
        entreprise,
        "Caisse",
        queryset=Caisse.objects.select_related("entreprise"),
    )
    session_obj = _resolve_session(session_caisse, entreprise, caisse_obj)

    if session_obj is not None and caisse_obj is None:
        caisse_obj = session_obj.caisse
    if (
        session_obj is None
        and caisse_obj is not None
        and method == PaymentTransaction.Method.CASH
        and desired_status == PaymentTransaction.Status.CONFIRME
    ):
        session_obj = (
            SessionCaisse.objects.filter(
                entreprise=entreprise,
                caisse=caisse_obj,
                statut=SessionCaisse.Statut.OUVERTE,
            )
            .order_by("-date_ouverture", "-id")
            .first()
        )
    if caisse_obj is not None and not caisse_obj.est_active:
        raise PaymentOperationError("La caisse selectionnee est inactive.")
    if facture_obj is not None and transaction_type != PaymentTransaction.TransactionType.ENCAISSEMENT:
        raise PaymentOperationError("Une facture ne peut etre liee qu'a un encaissement.")

    transaction_obj = PaymentTransaction.objects.create(
        entreprise=entreprise,
        transaction_type=transaction_type,
        method=method,
        amount=_normalize_amount(amount),
        currency=(currency or getattr(entreprise, "devise", "") or "CDF").strip().upper(),
        reference=reference,
        phone_number=phone_number,
        mobile_operator=mobile_operator if method in PaymentTransaction.MOBILE_MONEY_METHODS else "",
        status=PaymentTransaction.Status.EN_ATTENTE,
        transaction_date=transaction_date or timezone.now(),
        facture=facture_obj,
        depense=depense_obj,
        caisse=caisse_obj,
        session_caisse=session_obj,
        note=note,
        attachment=attachment,
        created_by=utilisateur,
    )
    _audit_payment(
        transaction_obj,
        utilisateur=utilisateur,
        action="payment_transaction_created",
        description="Paiement enregistre.",
    )

    if desired_status == PaymentTransaction.Status.CONFIRME:
        return confirm_payment_transaction(transaction_obj=transaction_obj, utilisateur=utilisateur)
    return transaction_obj


@transaction.atomic
def confirm_payment_transaction(*, transaction_obj, utilisateur):
    if not user_has_permission(utilisateur, "payments.validate"):
        raise PermissionDenied("Vous n'avez pas les droits pour confirmer un paiement.")

    locked = (
        _select_for_update_self(PaymentTransaction.objects.select_related("entreprise", "facture", "caisse", "session_caisse"))
        .filter(id=transaction_obj.id, entreprise=transaction_obj.entreprise)
        .first()
    )
    if locked is None:
        raise PaymentOperationError("Paiement introuvable.")
    if locked.status == PaymentTransaction.Status.CONFIRME:
        return locked
    if locked.status != PaymentTransaction.Status.EN_ATTENTE:
        raise PaymentOperationError("Seuls les paiements en attente peuvent etre confirmes.")

    locked.status = PaymentTransaction.Status.CONFIRME
    locked.validation_date = timezone.now()
    locked.validated_by = utilisateur
    locked.save(update_fields=["status", "validation_date", "validated_by", "updated_at"])

    if locked.facture_id:
        locked = _link_invoice_payment(locked, utilisateur)
    else:
        locked = _create_cash_movement(locked, utilisateur)

    _audit_payment(
        locked,
        utilisateur=utilisateur,
        action="payment_transaction_confirmed",
        description="Paiement confirme.",
    )
    return locked


@transaction.atomic
def reject_payment_transaction(*, transaction_obj, utilisateur, note=""):
    if not user_has_permission(utilisateur, "payments.validate"):
        raise PermissionDenied("Vous n'avez pas les droits pour rejeter un paiement.")

    locked = _select_for_update_self(PaymentTransaction.objects.all()).filter(
        id=transaction_obj.id,
        entreprise=transaction_obj.entreprise,
    ).first()
    if locked is None:
        raise PaymentOperationError("Paiement introuvable.")
    if locked.status != PaymentTransaction.Status.EN_ATTENTE:
        raise PaymentOperationError("Seuls les paiements en attente peuvent etre rejetes.")

    if note:
        locked.note = f"{locked.note}\nRejet: {note}".strip()
    locked.status = PaymentTransaction.Status.REJETE
    locked.validation_date = timezone.now()
    locked.validated_by = utilisateur
    locked.save(update_fields=["status", "validation_date", "validated_by", "note", "updated_at"])
    _audit_payment(
        locked,
        utilisateur=utilisateur,
        action="payment_transaction_rejected",
        description="Paiement rejete.",
        extra_metadata={"rejection_note": note},
    )
    return locked


@transaction.atomic
def cancel_payment_transaction(*, transaction_obj, utilisateur, note=""):
    if not user_has_permission(utilisateur, "payments.cancel"):
        raise PermissionDenied("Vous n'avez pas les droits pour annuler un paiement.")

    locked = _select_for_update_self(PaymentTransaction.objects.all()).filter(
        id=transaction_obj.id,
        entreprise=transaction_obj.entreprise,
    ).first()
    if locked is None:
        raise PaymentOperationError("Paiement introuvable.")
    if locked.status == PaymentTransaction.Status.ANNULE:
        return locked
    if locked.status == PaymentTransaction.Status.CONFIRME and (
        locked.paiement_facture_id or locked.mouvement_caisse_id
    ):
        raise PaymentOperationError(
            "Ce paiement confirme a deja impacte la facture ou la caisse. Enregistrez une correction separee."
        )

    if note:
        locked.note = f"{locked.note}\nAnnulation: {note}".strip()
    locked.status = PaymentTransaction.Status.ANNULE
    locked.cancelled_by = utilisateur
    locked.cancelled_at = timezone.now()
    locked.save(update_fields=["status", "cancelled_by", "cancelled_at", "note", "updated_at"])
    _audit_payment(
        locked,
        utilisateur=utilisateur,
        action="payment_transaction_cancelled",
        description="Paiement annule.",
        extra_metadata={"cancellation_note": note},
    )
    return locked
