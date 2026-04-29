from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.permissions import permission_required

from .forms import ConversationCreateForm, MessageReplyForm, PublicQuestionForm, SuggestionSuperAdminForm
from .models import PublicQuestion, SuggestionSuperAdmin
from .selectors.messages import (
    get_attachment_for_user,
    get_conversation_for_user,
    get_conversations_for_user,
    get_suggestions_for_entreprise,
    get_super_admin_public_questions,
    get_super_admin_suggestions,
    with_unread_counts,
)
from .services.messages import (
    create_conversation,
    create_public_question,
    create_suggestion_for_super_admin,
    mark_conversation_read,
    send_message,
    update_public_question_status,
    update_suggestion_status,
)


@permission_required("messages.view")
def conversation_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    conversations = with_unread_counts(get_conversations_for_user(request.user), request.user)
    return render(
        request,
        "joatham_messages/conversation_list.html",
        {
            "entreprise": entreprise,
            "conversations": conversations,
        },
    )


@permission_required("messages.view")
def conversation_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = ConversationCreateForm(request.POST or None, entreprise=entreprise, current_user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            conversation = create_conversation(
                entreprise=entreprise,
                creator=request.user,
                subject=form.cleaned_data["sujet"],
                participant_ids=[user.id for user in form.cleaned_data["participants"]],
                content=form.cleaned_data["contenu"],
                attachments=request.FILES.getlist("attachments"),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Conversation creee.")
            return redirect("message_conversation_detail", conversation_id=conversation.id)

    return render(request, "joatham_messages/conversation_form.html", {"form": form})


@permission_required("messages.view")
def conversation_detail(request, conversation_id):
    conversation = get_conversation_for_user(request.user, conversation_id)
    mark_conversation_read(conversation=conversation, user=request.user)
    messages_qs = conversation.messages.select_related("expediteur").prefetch_related("pieces_jointes", "lecteurs")
    return render(
        request,
        "joatham_messages/conversation_detail.html",
        {
            "conversation": conversation,
            "conversation_messages": messages_qs,
            "reply_form": MessageReplyForm(),
        },
    )


@require_POST
@permission_required("messages.view")
def send_conversation_message(request, conversation_id):
    conversation = get_conversation_for_user(request.user, conversation_id)
    form = MessageReplyForm(request.POST)
    if form.is_valid():
        try:
            send_message(
                conversation=conversation,
                sender=request.user,
                content=form.cleaned_data["contenu"],
                attachments=request.FILES.getlist("attachments"),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Message envoye.")
    else:
        messages.error(request, "Veuillez renseigner un message.")
    return redirect("message_conversation_detail", conversation_id=conversation.id)


@permission_required("messages.view")
def download_attachment(request, attachment_id):
    attachment = get_attachment_for_user(request.user, attachment_id)
    try:
        return FileResponse(
            attachment.fichier.open("rb"),
            as_attachment=True,
            filename=attachment.nom_original,
            content_type=attachment.type_contenu or None,
        )
    except FileNotFoundError as exc:
        raise Http404("Piece jointe introuvable.") from exc


@permission_required("suggestions.create")
def suggestion_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = SuggestionSuperAdminForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_suggestion_for_super_admin(
                entreprise=entreprise,
                user=request.user,
                subject=form.cleaned_data["sujet"],
                message=form.cleaned_data["message"],
            )
        except PermissionDenied as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Suggestion transmise au super admin.")
            return redirect("message_suggestion_create")

    return render(
        request,
        "joatham_messages/suggestion_form.html",
        {
            "form": form,
            "suggestions": get_suggestions_for_entreprise(entreprise),
        },
    )


def public_question_create(request):
    form = PublicQuestionForm(request.POST or None)
    submitted = False
    if request.method == "POST" and form.is_valid():
        create_public_question(
            nom=form.cleaned_data["nom"],
            email=form.cleaned_data["email"],
            telephone=form.cleaned_data.get("telephone", ""),
            subject=form.cleaned_data["sujet"],
            message=form.cleaned_data["message"],
        )
        submitted = True
        form = PublicQuestionForm()

    return render(
        request,
        "joatham_messages/public_question_form.html",
        {
            "form": form,
            "submitted": submitted,
        },
    )


@permission_required("superadmin.view")
def super_admin_messages(request):
    if request.method == "POST":
        item_type = (request.POST.get("item_type") or "").strip()
        item_id = request.POST.get("item_id")
        status = (request.POST.get("status") or "").strip()
        try:
            if item_type == "suggestion":
                suggestion = get_object_or_404(SuggestionSuperAdmin, id=item_id)
                update_suggestion_status(suggestion=suggestion, status=status)
                messages.success(request, "Statut de suggestion mis a jour.")
            elif item_type == "question":
                question = get_object_or_404(PublicQuestion, id=item_id)
                update_public_question_status(question=question, status=status)
                messages.success(request, "Statut de question mis a jour.")
            else:
                messages.error(request, "Action inconnue.")
        except ValidationError as exc:
            messages.error(request, str(exc))
        return redirect("super_admin_messages")

    return render(
        request,
        "joatham_messages/super_admin_messages.html",
        {
            "suggestions": get_super_admin_suggestions(),
            "public_questions": get_super_admin_public_questions(),
            "suggestion_statuses": SuggestionSuperAdmin.Statut.choices,
            "question_statuses": PublicQuestion.Statut.choices,
        },
    )
