import logging
import os

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from core.audit import record_audit_event
from core.models import PlatformSettings
from joatham_users.models import User

from ..models import Conversation, Message, MessageAttachment, PublicQuestion, SuggestionSuperAdmin


logger = logging.getLogger(__name__)

MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
MAX_MESSAGE_LENGTH = 5000
FINAL_STATUSES = {
    SuggestionSuperAdmin.Statut.TRAITE,
    SuggestionSuperAdmin.Statut.REJETE,
    SuggestionSuperAdmin.Statut.ARCHIVE,
}
DANGEROUS_ATTACHMENT_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".exe",
    ".html",
    ".js",
    ".php",
    ".ps1",
    ".sh",
    ".vbs",
}


def _ensure_company_user(user, entreprise):
    if not user or not getattr(user, "is_authenticated", False) or getattr(user, "entreprise_id", None) != entreprise.id:
        raise PermissionDenied("Utilisateur hors entreprise.")


def _clean_required_text(value, *, field_label, max_length=MAX_MESSAGE_LENGTH, min_length=1):
    value = (value or "").strip()
    if not value:
        raise ValidationError(f"{field_label} est obligatoire.")
    if min_length and len(value) < min_length:
        raise ValidationError(f"{field_label} doit contenir au moins {min_length} caracteres.")
    if max_length and len(value) > max_length:
        raise ValidationError(f"{field_label} ne doit pas depasser {max_length} caracteres.")
    return value


def _validate_attachments(uploaded_files):
    files = list(uploaded_files or [])
    if len(files) > MAX_ATTACHMENTS:
        raise ValidationError(f"Maximum {MAX_ATTACHMENTS} pieces jointes par message.")
    for uploaded_file in files:
        original_name = os.path.basename(getattr(uploaded_file, "name", "") or "piece-jointe")
        extension = os.path.splitext(original_name)[1].lower()
        if extension in DANGEROUS_ATTACHMENT_EXTENSIONS:
            raise ValidationError("Ce type de piece jointe n'est pas autorise.")
        if (getattr(uploaded_file, "size", 0) or 0) > MAX_ATTACHMENT_SIZE:
            raise ValidationError("Une piece jointe depasse la taille maximale autorisee de 10 Mo.")
    return files


def _record_message_event(*, entreprise, utilisateur=None, action, objet_type, objet_id, description, metadata=None):
    return record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action=action,
        module="messages",
        objet_type=objet_type,
        objet_id=objet_id,
        description=description,
        metadata=metadata or {},
    )


def _get_super_admin_recipients():
    recipients = list(
        User.objects.filter(role=User.Role.SUPER_ADMIN, is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    platform_email = ""
    try:
        platform_email = PlatformSettings.get_solo().email_systeme
    except Exception:
        logger.exception("Impossible de lire l'adresse systeme pour la notification de demande SaaS.")
    if platform_email:
        recipients.append(platform_email)
    return sorted({email.strip().lower() for email in recipients if email and email.strip()})


def _notify_super_admins_new_request(*, subject, body):
    recipients = _get_super_admin_recipients()
    if not recipients:
        return
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            recipients,
            fail_silently=False,
        )
    except Exception:
        logger.exception("Echec de notification e-mail pour une nouvelle demande SaaS.")


def _get_participants(entreprise, participant_ids, creator):
    ids = {int(user_id) for user_id in participant_ids if str(user_id).strip().isdigit()}
    ids.add(creator.id)
    participants = list(User.objects.filter(entreprise=entreprise, is_active=True, id__in=ids))
    if creator.id not in {participant.id for participant in participants}:
        raise PermissionDenied("Le createur doit appartenir a l'entreprise.")
    if len(participants) != len(ids):
        raise PermissionDenied("Un participant ne fait pas partie de votre entreprise.")
    return participants


def _create_attachments(message, uploaded_files):
    attachments = []
    for uploaded_file in _validate_attachments(uploaded_files):
        original_name = os.path.basename(getattr(uploaded_file, "name", "") or "piece-jointe")
        attachments.append(
            MessageAttachment.objects.create(
                message=message,
                fichier=uploaded_file,
                nom_original=original_name[:255],
                type_contenu=getattr(uploaded_file, "content_type", "") or "",
                taille=getattr(uploaded_file, "size", 0) or 0,
            )
        )
    return attachments


@transaction.atomic
def create_conversation(*, entreprise, creator, subject, participant_ids, content, attachments=None):
    _ensure_company_user(creator, entreprise)
    subject = _clean_required_text(subject, field_label="Le sujet", max_length=180)
    content = _clean_required_text(content, field_label="Le message")
    attachments = _validate_attachments(attachments)

    participants = _get_participants(entreprise, participant_ids, creator)
    conversation = Conversation.objects.create(entreprise=entreprise, sujet=subject, cree_par=creator)
    conversation.participants.set(participants)
    message = Message.objects.create(
        entreprise=entreprise,
        conversation=conversation,
        expediteur=creator,
        contenu=content,
    )
    message.lecteurs.add(creator)
    _create_attachments(message, attachments)
    _record_message_event(
        entreprise=entreprise,
        utilisateur=creator,
        action="message_interne_cree",
        objet_type="Message",
        objet_id=message.id,
        description=f"Message cree dans la conversation : {conversation.sujet}.",
        metadata={"conversation_id": conversation.id, "sujet": conversation.sujet},
    )
    return conversation


@transaction.atomic
def send_message(*, conversation, sender, content, attachments=None):
    _ensure_company_user(sender, conversation.entreprise)
    if not conversation.participants.filter(id=sender.id).exists():
        raise PermissionDenied("Vous ne participez pas a cette conversation.")
    content = (content or "").strip()
    attachments = _validate_attachments(attachments)
    if not content and not attachments:
        raise ValidationError("Le message est obligatoire.")
    if len(content) > MAX_MESSAGE_LENGTH:
        raise ValidationError(f"Le message ne doit pas depasser {MAX_MESSAGE_LENGTH} caracteres.")

    message = Message.objects.create(
        entreprise=conversation.entreprise,
        conversation=conversation,
        expediteur=sender,
        contenu=content,
    )
    message.lecteurs.add(sender)
    _create_attachments(message, attachments)
    conversation.date_modification = timezone.now()
    conversation.save(update_fields=["date_modification"])
    _record_message_event(
        entreprise=conversation.entreprise,
        utilisateur=sender,
        action="message_interne_cree",
        objet_type="Message",
        objet_id=message.id,
        description=f"Message envoye dans la conversation : {conversation.sujet}.",
        metadata={"conversation_id": conversation.id, "sujet": conversation.sujet},
    )
    return message


def mark_conversation_read(*, conversation, user):
    _ensure_company_user(user, conversation.entreprise)
    if not conversation.participants.filter(id=user.id).exists():
        raise PermissionDenied("Vous ne participez pas a cette conversation.")
    unread_messages = conversation.messages.exclude(expediteur=user).exclude(lecteurs=user)
    for message in unread_messages:
        message.lecteurs.add(user)


@transaction.atomic
def create_suggestion_for_super_admin(*, entreprise, user, subject, message):
    _ensure_company_user(user, entreprise)
    if getattr(user, "normalized_role", getattr(user, "role", "")) != User.Role.PROPRIETAIRE:
        raise PermissionDenied("Seul le proprietaire peut envoyer une suggestion.")
    subject = _clean_required_text(subject, field_label="Le sujet", max_length=180)
    message = _clean_required_text(message, field_label="La suggestion", min_length=10)
    suggestion = SuggestionSuperAdmin.objects.create(
        entreprise=entreprise,
        utilisateur=user,
        sujet=subject,
        message=message,
    )
    _record_message_event(
        entreprise=entreprise,
        utilisateur=user,
        action="suggestion_creee",
        objet_type="SuggestionSuperAdmin",
        objet_id=suggestion.id,
        description=f"Suggestion transmise au super admin : {suggestion.sujet}.",
        metadata={"statut": suggestion.statut},
    )
    _notify_super_admins_new_request(
        subject=f"Nouvelle suggestion JOATHAM Manager - {entreprise.nom}",
        body=(
            f"Entreprise : {entreprise.nom}\n"
            f"Utilisateur : {user.get_full_name() or user.username}\n"
            f"Sujet : {suggestion.sujet}\n\n"
            f"{suggestion.message}"
        ),
    )
    return suggestion


@transaction.atomic
def create_public_question(*, nom, email, telephone, entreprise="", subject, message):
    question = PublicQuestion.objects.create(
        nom=_clean_required_text(nom, field_label="Le nom", max_length=150),
        email=_clean_required_text(email, field_label="L'email", max_length=254).lower(),
        telephone=(telephone or "").strip(),
        entreprise=(entreprise or "").strip(),
        sujet=_clean_required_text(subject, field_label="Le sujet", max_length=180),
        message=_clean_required_text(message, field_label="Le message", min_length=10),
    )
    _record_message_event(
        entreprise=None,
        utilisateur=None,
        action="question_publique_creee",
        objet_type="PublicQuestion",
        objet_id=question.id,
        description=f"Question publique recue avant inscription : {question.sujet}.",
        metadata={
            "nom": question.nom,
            "email": question.email,
            "telephone_renseigne": bool(question.telephone),
            "entreprise": question.entreprise,
            "statut": question.statut,
        },
    )
    _notify_super_admins_new_request(
        subject="Nouvelle question avant inscription - JOATHAM Manager",
        body=(
            f"Nom : {question.nom}\n"
            f"Email : {question.email}\n"
            f"Telephone : {question.telephone or '-'}\n"
            f"Entreprise : {question.entreprise or '-'}\n"
            f"Sujet : {question.sujet}\n\n"
            f"{question.message}"
        ),
    )
    return question


def _apply_status(instance, status):
    instance.statut = status
    instance.date_traitement = timezone.now() if status in FINAL_STATUSES else None


def update_suggestion_status(*, suggestion, status, changed_by=None):
    if status not in SuggestionSuperAdmin.Statut.values:
        raise ValidationError("Statut de suggestion invalide.")
    old_status = suggestion.statut
    if old_status == status:
        return suggestion
    _apply_status(suggestion, status)
    suggestion.save(update_fields=["statut", "date_traitement", "date_modification"])
    _record_message_event(
        entreprise=suggestion.entreprise,
        utilisateur=changed_by,
        action="suggestion_statut_modifie",
        objet_type="SuggestionSuperAdmin",
        objet_id=suggestion.id,
        description=f"Statut de suggestion modifie : {old_status} -> {status}.",
        metadata={"ancien_statut": old_status, "nouveau_statut": status},
    )
    return suggestion


def update_public_question_status(*, question, status, changed_by=None):
    if status not in PublicQuestion.Statut.values:
        raise ValidationError("Statut de question invalide.")
    old_status = question.statut
    if old_status == status:
        return question
    _apply_status(question, status)
    question.save(update_fields=["statut", "date_traitement", "date_modification"])
    _record_message_event(
        entreprise=None,
        utilisateur=changed_by,
        action="question_publique_statut_modifie",
        objet_type="PublicQuestion",
        objet_id=question.id,
        description=f"Statut de question publique modifie : {old_status} -> {status}.",
        metadata={"ancien_statut": old_status, "nouveau_statut": status},
    )
    return question
