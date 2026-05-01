from django.db.models import Count, Q
from django.shortcuts import get_object_or_404

from joatham_users.models import User

from ..models import Conversation, Message, MessageAttachment, PublicQuestion, SuggestionSuperAdmin


OPEN_STATUSES = (
    SuggestionSuperAdmin.Statut.NOUVEAU,
    SuggestionSuperAdmin.Statut.EN_COURS,
)

REQUEST_TYPE_SUGGESTION = "suggestion"
REQUEST_TYPE_QUESTION = "question"


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


def _apply_common_filters(queryset, *, filters, search_query):
    selected_status = filters.get("statut") if filters else ""
    date_from = filters.get("date_from") if filters else None
    date_to = filters.get("date_to") if filters else None

    if selected_status:
        queryset = queryset.filter(statut=selected_status)
    if date_from:
        queryset = queryset.filter(date_creation__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(date_creation__date__lte=date_to)
    if search_query is not None:
        queryset = queryset.filter(search_query)
    return queryset


def get_super_admin_suggestions(filters=None):
    filters = filters or {}
    selected_type = filters.get("type") or ""
    if selected_type == REQUEST_TYPE_QUESTION:
        return SuggestionSuperAdmin.objects.none()
    search = (filters.get("q") or "").strip()
    search_query = None
    if search:
        search_query = (
            Q(sujet__icontains=search)
            | Q(message__icontains=search)
            | Q(entreprise__nom__icontains=search)
            | Q(utilisateur__username__icontains=search)
            | Q(utilisateur__email__icontains=search)
            | Q(utilisateur__first_name__icontains=search)
            | Q(utilisateur__last_name__icontains=search)
        )
    return _apply_common_filters(
        SuggestionSuperAdmin.objects.select_related("entreprise", "utilisateur").order_by("-date_creation", "-id"),
        filters=filters,
        search_query=search_query,
    )


def get_suggestion_for_super_admin(suggestion_id):
    return get_object_or_404(SuggestionSuperAdmin.objects.select_related("entreprise", "utilisateur"), id=suggestion_id)


def get_super_admin_public_questions(filters=None):
    filters = filters or {}
    selected_type = filters.get("type") or ""
    if selected_type == REQUEST_TYPE_SUGGESTION:
        return PublicQuestion.objects.none()
    search = (filters.get("q") or "").strip()
    search_query = None
    if search:
        search_query = (
            Q(sujet__icontains=search)
            | Q(message__icontains=search)
            | Q(nom__icontains=search)
            | Q(email__icontains=search)
            | Q(telephone__icontains=search)
            | Q(entreprise__icontains=search)
            | Q(reponse__icontains=search)
            | Q(repondu_par__username__icontains=search)
            | Q(repondu_par__email__icontains=search)
        )
    return _apply_common_filters(
        PublicQuestion.objects.select_related("repondu_par").order_by("-date_creation", "-id"),
        filters=filters,
        search_query=search_query,
    )


def get_public_question_for_super_admin(question_id):
    return get_object_or_404(PublicQuestion.objects.select_related("repondu_par"), id=question_id)


def _suggestion_to_request_item(suggestion):
    return {
        "type": REQUEST_TYPE_SUGGESTION,
        "type_label": "Suggestion",
        "id": suggestion.id,
        "auteur": suggestion.utilisateur.get_full_name() or suggestion.utilisateur.username,
        "entreprise": suggestion.entreprise.nom,
        "email": suggestion.utilisateur.email,
        "telephone": getattr(suggestion.utilisateur, "telephone", ""),
        "sujet": suggestion.sujet,
        "message": suggestion.message,
        "statut": suggestion.statut,
        "statut_label": suggestion.get_statut_display(),
        "date_creation": suggestion.date_creation,
        "date_traitement": suggestion.date_traitement,
    }


def _public_question_to_request_item(question):
    repondu_par = ""
    if question.repondu_par:
        repondu_par = question.repondu_par.get_full_name() or question.repondu_par.username
    return {
        "type": REQUEST_TYPE_QUESTION,
        "type_label": "Question publique",
        "id": question.id,
        "auteur": question.nom,
        "entreprise": question.entreprise,
        "email": question.email,
        "telephone": question.telephone,
        "sujet": question.sujet,
        "message": question.message,
        "statut": question.statut,
        "statut_label": question.get_statut_display(),
        "date_creation": question.date_creation,
        "date_traitement": question.date_traitement,
        "has_reply": bool(question.reponse),
        "date_reponse": question.date_reponse,
        "repondu_par": repondu_par,
    }


def get_super_admin_request_items(filters=None):
    suggestions = [_suggestion_to_request_item(suggestion) for suggestion in get_super_admin_suggestions(filters)]
    questions = [_public_question_to_request_item(question) for question in get_super_admin_public_questions(filters)]
    return sorted(
        suggestions + questions,
        key=lambda item: (item["date_creation"], item["id"]),
        reverse=True,
    )


def get_super_admin_request_summary():
    return {
        "suggestions": SuggestionSuperAdmin.objects.count(),
        "questions": PublicQuestion.objects.count(),
        "nouveau": SuggestionSuperAdmin.objects.filter(statut=SuggestionSuperAdmin.Statut.NOUVEAU).count()
        + PublicQuestion.objects.filter(statut=PublicQuestion.Statut.NOUVEAU).count(),
        "en_cours": SuggestionSuperAdmin.objects.filter(statut=SuggestionSuperAdmin.Statut.EN_COURS).count()
        + PublicQuestion.objects.filter(statut=PublicQuestion.Statut.EN_COURS).count(),
    }


def get_pending_super_admin_message_count():
    return SuggestionSuperAdmin.objects.filter(statut__in=OPEN_STATUSES).count() + PublicQuestion.objects.filter(statut__in=OPEN_STATUSES).count()
