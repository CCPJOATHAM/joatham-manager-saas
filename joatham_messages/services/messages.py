from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from joatham_users.models import User

from ..models import Conversation, Message, MessageAttachment, PublicQuestion, SuggestionSuperAdmin


def _ensure_company_user(user, entreprise):
    if not user or not getattr(user, "is_authenticated", False) or getattr(user, "entreprise_id", None) != entreprise.id:
        raise PermissionDenied("Utilisateur hors entreprise.")


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
    for uploaded_file in uploaded_files or []:
        attachments.append(
            MessageAttachment.objects.create(
                message=message,
                fichier=uploaded_file,
                nom_original=getattr(uploaded_file, "name", "") or "piece-jointe",
                type_contenu=getattr(uploaded_file, "content_type", "") or "",
                taille=getattr(uploaded_file, "size", 0) or 0,
            )
        )
    return attachments


@transaction.atomic
def create_conversation(*, entreprise, creator, subject, participant_ids, content, attachments=None):
    _ensure_company_user(creator, entreprise)
    subject = (subject or "").strip()
    content = (content or "").strip()
    if not subject:
        raise ValidationError("Le sujet est obligatoire.")
    if not content:
        raise ValidationError("Le message est obligatoire.")

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
    return conversation


@transaction.atomic
def send_message(*, conversation, sender, content, attachments=None):
    _ensure_company_user(sender, conversation.entreprise)
    if not conversation.participants.filter(id=sender.id).exists():
        raise PermissionDenied("Vous ne participez pas a cette conversation.")
    content = (content or "").strip()
    if not content and not attachments:
        raise ValidationError("Le message est obligatoire.")

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
    return message


def mark_conversation_read(*, conversation, user):
    _ensure_company_user(user, conversation.entreprise)
    if not conversation.participants.filter(id=user.id).exists():
        raise PermissionDenied("Vous ne participez pas a cette conversation.")
    unread_messages = conversation.messages.exclude(expediteur=user).exclude(lecteurs=user)
    for message in unread_messages:
        message.lecteurs.add(user)


def create_suggestion_for_super_admin(*, entreprise, user, subject, message):
    _ensure_company_user(user, entreprise)
    if getattr(user, "normalized_role", getattr(user, "role", "")) != User.Role.PROPRIETAIRE:
        raise PermissionDenied("Seul le proprietaire peut envoyer une suggestion.")
    return SuggestionSuperAdmin.objects.create(
        entreprise=entreprise,
        utilisateur=user,
        sujet=(subject or "").strip(),
        message=(message or "").strip(),
    )


def create_public_question(*, nom, email, telephone, subject, message):
    return PublicQuestion.objects.create(
        nom=(nom or "").strip(),
        email=(email or "").strip().lower(),
        telephone=(telephone or "").strip(),
        sujet=(subject or "").strip(),
        message=(message or "").strip(),
    )


def update_suggestion_status(*, suggestion, status):
    if status not in SuggestionSuperAdmin.Statut.values:
        raise ValidationError("Statut de suggestion invalide.")
    suggestion.statut = status
    suggestion.save(update_fields=["statut", "date_modification"])
    return suggestion


def update_public_question_status(*, question, status):
    if status not in PublicQuestion.Statut.values:
        raise ValidationError("Statut de question invalide.")
    question.statut = status
    question.save(update_fields=["statut", "date_modification"])
    return question
