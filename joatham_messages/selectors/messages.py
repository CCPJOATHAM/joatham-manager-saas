from django.db.models import Count
from django.shortcuts import get_object_or_404

from joatham_users.models import User

from ..models import Conversation, Message, MessageAttachment, PublicQuestion, SuggestionSuperAdmin


OPEN_STATUSES = (
    SuggestionSuperAdmin.Statut.NOUVEAU,
    SuggestionSuperAdmin.Statut.EN_COURS,
)


def get_company_users_for_messaging(entreprise, *, exclude_user=None):
    users = User.objects.filter(entreprise=entreprise, is_active=True).order_by("first_name", "last_name", "username")
    if exclude_user is not None:
        users = users.exclude(id=exclude_user.id)
    return users


def get_conversations_for_user(user):
    return (
        Conversation.objects.filter(entreprise=user.entreprise, participants=user)
        .select_related("entreprise", "cree_par")
        .prefetch_related("participants")
        .order_by("-date_modification", "-id")
    )


def with_unread_counts(conversations, user):
    conversations = list(conversations)
    unread_rows = (
        Message.objects.filter(conversation__in=conversations)
        .exclude(expediteur=user)
        .exclude(lecteurs=user)
        .values("conversation_id")
        .annotate(total=Count("id"))
    )
    unread_by_conversation = {row["conversation_id"]: row["total"] for row in unread_rows}
    for conversation in conversations:
        conversation.unread_count = unread_by_conversation.get(conversation.id, 0)
    return conversations


def get_conversation_for_user(user, conversation_id):
    return get_object_or_404(
        get_conversations_for_user(user).prefetch_related("messages__expediteur", "messages__pieces_jointes"),
        id=conversation_id,
    )


def get_unread_message_count(user):
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "entreprise_id", None):
        return 0
    return (
        Message.objects.filter(entreprise=user.entreprise, conversation__participants=user)
        .exclude(expediteur=user)
        .exclude(lecteurs=user)
        .count()
    )


def get_attachment_for_user(user, attachment_id):
    return get_object_or_404(
        MessageAttachment.objects.select_related("message__conversation").filter(
            message__conversation__entreprise=user.entreprise,
            message__conversation__participants=user,
        ),
        id=attachment_id,
    )


def get_suggestions_for_entreprise(entreprise):
    return SuggestionSuperAdmin.objects.filter(entreprise=entreprise).select_related("utilisateur").order_by("-date_creation", "-id")


def get_super_admin_suggestions():
    return SuggestionSuperAdmin.objects.select_related("entreprise", "utilisateur").order_by("-date_creation", "-id")


def get_super_admin_public_questions():
    return PublicQuestion.objects.order_by("-date_creation", "-id")


def get_pending_super_admin_message_count():
    return SuggestionSuperAdmin.objects.filter(statut__in=OPEN_STATUSES).count() + PublicQuestion.objects.filter(statut__in=OPEN_STATUSES).count()
