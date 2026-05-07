from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.permissions import permission_required
from joatham_users.services.invitations import InvitationEmailError

from .forms import (
    ConversationCreateForm,
    MessageReplyForm,
    PublicQuestionReplyForm,
    PublicQuestionForm,
    SuggestionSuperAdminForm,
    SuperAdminRequestFilterForm,
    SuperAdminStatusUpdateForm,
)
from .models import PublicQuestion, SuggestionSuperAdmin
from .selectors.messages import (
    get_attachment_for_user,
    get_conversation_for_user,
    get_conversations_for_user,
    get_lead_stats,
    get_public_question_for_super_admin,
    get_suggestions_for_entreprise,
    get_suggestion_for_super_admin,
    get_super_admin_request_items,
    get_super_admin_request_summary,
    with_unread_counts,
)
from .services.messages import (
    create_conversation,
    create_invitation_from_public_question,
    create_public_question,
    create_suggestion_for_super_admin,
    answer_public_question,
    mark_conversation_read,
    PublicQuestionReplyEmailError,
    send_message,
    update_public_question_lead_status,
    update_public_question_status,
    update_suggestion_status,
)


@permission_required("messages.view")
@module_access_required("messages")
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
@module_access_required("messages")
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
@module_access_required("messages")
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
@module_access_required("messages")
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
@module_access_required("messages")
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
        except (PermissionDenied, ValidationError) as exc:
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
    if request.method == "POST" and form.is_valid():
        try:
            create_public_question(
                nom=form.cleaned_data["nom"],
                email=form.cleaned_data["email"],
                telephone=form.cleaned_data.get("telephone", ""),
                entreprise=form.cleaned_data.get("entreprise", ""),
                subject=form.cleaned_data["sujet"],
                message=form.cleaned_data["message"],
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        else:
            return redirect("public_question_success")

    return render(
        request,
        "joatham_messages/public_question_form.html",
        {
            "form": form,
        },
    )


def public_question_thanks(request):
    return render(request, "joatham_messages/public_question_thanks.html")


def public_question_success(request):
    return render(request, "joatham_messages/public_question_success.html")


@permission_required("superadmin.view")
def super_admin_public_question_reply(request, question_id):
    question = get_public_question_for_super_admin(question_id)
    form = PublicQuestionReplyForm(request.POST or None, initial={"reponse": question.reponse})

    if request.method == "POST" and form.is_valid():
        try:
            answer_public_question(
                question=question,
                responder=request.user,
                response=form.cleaned_data["reponse"],
            )
        except PublicQuestionReplyEmailError as exc:
            messages.error(request, str(exc))
            question = get_public_question_for_super_admin(question_id)
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Reponse envoyee au visiteur.")
            return redirect("super_admin_messages")

    return render(
        request,
        "joatham_messages/public_question_reply_form.html",
        {
            "question": question,
            "form": form,
        },
    )


@permission_required("superadmin.view")
def super_admin_messages(request):
    if request.method == "POST":
        form = SuperAdminStatusUpdateForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Action de statut invalide.")
            return redirect("super_admin_messages")
        try:
            if form.cleaned_data["item_type"] == "suggestion":
                suggestion = get_suggestion_for_super_admin(form.cleaned_data["item_id"])
                update_suggestion_status(
                    suggestion=suggestion,
                    status=form.cleaned_data["status"],
                    changed_by=request.user,
                )
                messages.success(request, "Statut de suggestion mis a jour.")
            elif form.cleaned_data["item_type"] == "question":
                question = get_public_question_for_super_admin(form.cleaned_data["item_id"])
                update_public_question_status(
                    question=question,
                    status=form.cleaned_data["status"],
                    changed_by=request.user,
                )
                messages.success(request, "Statut de question mis a jour.")
            else:
                messages.error(request, "Action inconnue.")
        except ValidationError as exc:
            messages.error(request, str(exc))
        return redirect("super_admin_messages")

    filter_form = SuperAdminRequestFilterForm(request.GET or None)
    filters = filter_form.cleaned_data if filter_form.is_valid() else {}
    if request.GET and not filter_form.is_valid():
        messages.error(request, "Certains filtres sont invalides.")
    selected_lead_status = (request.GET.get("status") or "").strip()
    valid_lead_statuses = {value for value, _label in PublicQuestion.LeadStatus.choices}
    if selected_lead_status not in valid_lead_statuses:
        selected_lead_status = ""
    if selected_lead_status:
        filters = {**filters, "lead_status": selected_lead_status}
    request_items = get_super_admin_request_items(filters)
    paginator = Paginator(request_items, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)

    return render(
        request,
        "joatham_messages/super_admin_messages.html",
        {
            "filter_form": filter_form,
            "requests": page_obj.object_list,
            "page_obj": page_obj,
            "status_choices": SuggestionSuperAdmin.Statut.choices,
            "lead_status_choices": PublicQuestion.LeadStatus.choices,
            "summary": get_super_admin_request_summary(),
            "lead_stats": get_lead_stats(),
            "selected_lead_status": selected_lead_status,
            "selected_filters": filters,
            "querystring_without_page": query_params.urlencode(),
        },
    )


@login_required
@permission_required("superadmin.view")
@require_POST
def update_lead_status(request, id):
    question = get_public_question_for_super_admin(id)
    lead_status = (request.POST.get("lead_status") or request.POST.get("status") or "").strip()
    try:
        update_public_question_lead_status(question=question, lead_status=lead_status)
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Statut CRM du lead mis a jour.")
    return redirect(request.META.get("HTTP_REFERER") or "super_admin_messages")


@login_required
@permission_required("superadmin.view")
@require_POST
def send_public_question_invitation(request, question_id):
    question = get_public_question_for_super_admin(question_id)
    try:
        result = create_invitation_from_public_question(question=question, created_by=request.user)
    except InvitationEmailError as exc:
        messages.error(request, str(exc))
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        if result.created:
            messages.success(request, "Invitation envoyee au lead.")
        else:
            messages.info(request, "Une invitation existe deja pour ce lead.")
    return redirect("super_admin_messages")
