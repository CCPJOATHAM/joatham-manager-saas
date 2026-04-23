from django.conf import settings
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetDoneView, PasswordResetView, PasswordResetCompleteView
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy

from core.audit import record_audit_event
from core.services.product_policy import get_module_label, module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from core.ui_text import FLASH_MESSAGES
from core.services.world import build_country_currency_map, get_currency_choices
from joatham_dashboard.forms import SecurePasswordResetForm, SignupForm
from joatham_dashboard.services.password_reset import (
    get_request_ip,
    is_password_reset_throttled,
    mark_password_reset_request,
)
from joatham_dashboard.services.email_verification import send_email_verification, verify_email_token
from joatham_dashboard.services.onboarding import register_entreprise_owner
from joatham_users.permissions import get_default_dashboard_name, permission_required, user_has_permission

from .services.dashboard_service import build_dashboard_context

User = get_user_model()


class SecurePasswordResetRequestView(PasswordResetView):
    form_class = SecurePasswordResetForm
    template_name = "joatham_dashboard/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    html_email_template_name = "registration/password_reset_email.html"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def form_valid(self, form):
        email = (form.cleaned_data.get("email") or "").strip().lower()
        ip_address = get_request_ip(self.request)

        if is_password_reset_throttled(email=email, ip_address=ip_address):
            return HttpResponseRedirect(self.get_success_url())

        mark_password_reset_request(email=email, ip_address=ip_address)
        form.save(
            use_https=self.request.is_secure(),
            token_generator=self.token_generator,
            from_email=self.from_email,
            email_template_name=self.email_template_name,
            subject_template_name=self.subject_template_name,
            request=self.request,
            html_email_template_name=self.html_email_template_name,
            extra_email_context=self.extra_email_context,
        )
        return HttpResponseRedirect(self.get_success_url())


class SecurePasswordResetDoneView(PasswordResetDoneView):
    template_name = "joatham_dashboard/password_reset_done.html"


class SecurePasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "joatham_dashboard/password_reset_confirm.html"
    success_url = reverse_lazy("password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = getattr(self, "user", None)
        entreprise = getattr(user, "entreprise", None)
        if user is not None and entreprise is not None:
            record_audit_event(
                entreprise=entreprise,
                utilisateur=user,
                action="password_reset_completed",
                module="auth",
                objet_type="User",
                objet_id=user.id,
                description=f"Mot de passe réinitialisé pour {user.username}.",
                metadata={"email": user.email},
            )
        return response


class SecurePasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "joatham_dashboard/password_reset_complete.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["login_url"] = reverse_lazy("login")
        context["redirect_delay_seconds"] = 4
        return context


def login_view(request):
    if request.user.is_authenticated:
        messages.info(request, "Vous êtes déjà connecté. Déconnectez-vous pour accéder à la page de connexion ou créer une nouvelle entreprise.")
        return redirect(get_default_dashboard_name(request.user))

    error = None

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)

        if user is None and "@" in username:
            existing_user = User.objects.filter(email__iexact=username).first()
            if existing_user is not None:
                user = authenticate(request, username=existing_user.username, password=password)

        if user is not None:
            if not getattr(user, "email_verified", True):
                request.session["pending_verification_user_id"] = user.id
                messages.info(request, "Veuillez confirmer votre adresse email avant d'utiliser JOATHAM Manager.")
                return redirect("email_verification_sent")
            login(request, user)
            return redirect(get_default_dashboard_name(user))

        error = "Nom d'utilisateur ou mot de passe incorrect"

    return render(request, "joatham_dashboard/login.html", {"error": error, "app_name": "JOATHAM Manager"})


def signup_view(request):
    if request.user.is_authenticated:
        messages.info(request, "Vous êtes déjà connecté. Déconnectez-vous pour créer une autre entreprise ou tester le parcours d'inscription.")
        return redirect(get_default_dashboard_name(request.user))

    form = SignupForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            user = register_entreprise_owner(
                company_name=form.cleaned_data["company_name"],
                raison_sociale=form.cleaned_data["raison_sociale"],
                owner_full_name=form.cleaned_data["owner_full_name"],
                email=form.cleaned_data["email"],
                telephone=form.cleaned_data["telephone"],
                pays=form.cleaned_data["pays"],
                devise=form.cleaned_data["devise"],
                password=form.cleaned_data["password"],
            )
        except ValueError as exc:
            form.add_error("email", str(exc))
        else:
            request.session["pending_verification_user_id"] = user.id
            send_email_verification(request, user)
            messages.success(request, "Un email de confirmation a été envoyé à votre adresse.")
            return redirect("email_verification_sent")

    return render(
        request,
        "joatham_dashboard/signup.html",
        {
            "form": form,
            "app_name": "JOATHAM Manager",
            "country_currency_map": build_country_currency_map(),
            "currency_choices": get_currency_choices(),
        },
    )


@permission_required("dashboard.owner")
@module_access_required("dashboard")
def admin_dashboard(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    return render(request, "joatham_dashboard/admin.html", build_dashboard_context(entreprise))


@permission_required("dashboard.management")
@module_access_required("dashboard")
def gestion_dashboard(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    return render(request, "joatham_dashboard/gestion.html", build_dashboard_context(entreprise))


@permission_required("dashboard.accounting")
@module_access_required("dashboard")
def comptable_dashboard(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    return render(request, "joatham_dashboard/comptable.html", build_dashboard_context(entreprise))


def home(request):
    return redirect("login")


def email_verification_sent_view(request):
    user = None
    pending_user_id = request.session.get("pending_verification_user_id")

    if request.user.is_authenticated and not getattr(request.user, "email_verified", True):
        user = request.user
    elif pending_user_id:
        user = User.objects.filter(id=pending_user_id).first()

    if user is not None and getattr(user, "email_verified", False):
        request.session.pop("pending_verification_user_id", None)
        request.session.pop("debug_email_verification_url", None)
        return redirect(get_default_dashboard_name(user))

    return render(
        request,
        "joatham_dashboard/email_verification_sent.html",
        {
            "pending_email": getattr(user, "email", ""),
            "expiration_minutes": max(1, int(getattr(settings, "EMAIL_VERIFICATION_TIMEOUT", 3600) / 60)),
            "debug_verification_url": request.session.get("debug_email_verification_url") if settings.DEBUG else "",
        },
    )


def email_verification_confirm_view(request, uidb64, token):
    user = verify_email_token(uidb64=uidb64, token=token)
    if user is None:
        return render(request, "joatham_dashboard/email_verification_invalid.html", status=400)

    if not user.email_verified:
        user.mark_email_verified()
        entreprise = getattr(user, "entreprise", None)
        if entreprise is not None:
            record_audit_event(
                entreprise=entreprise,
                utilisateur=user,
                action="email_verified",
                module="auth",
                objet_type="User",
                objet_id=user.id,
                description=f"Adresse email confirmee pour {user.email}.",
                metadata={"email": user.email},
            )

    request.session.pop("pending_verification_user_id", None)
    request.session.pop("debug_email_verification_url", None)
    return render(
        request,
        "joatham_dashboard/email_verification_complete.html",
        {"login_url": reverse("login")},
    )


def email_verification_resend_view(request):
    user = None
    pending_user_id = request.session.get("pending_verification_user_id")

    if request.user.is_authenticated and not getattr(request.user, "email_verified", True):
        user = request.user
    elif pending_user_id:
        user = User.objects.filter(id=pending_user_id).first()

    if request.method == "POST" and user is not None and not getattr(user, "email_verified", True):
        send_email_verification(request, user)
        messages.success(request, "Un nouvel email de confirmation a été envoyé.")

    return redirect("email_verification_sent")


def logout_view(request):
    logout(request)
    messages.success(request, FLASH_MESSAGES["logged_out"])
    return redirect("login")


def abonnement_expire(request):
    module_name = request.GET.get("module", "").strip()
    context = {
        "module_name": module_name,
        "module_label": get_module_label(module_name) if module_name else "",
        "reason": request.GET.get("reason", "").strip(),
        "show_subscription_link": user_has_permission(request.user, "subscription.view") if request.user.is_authenticated else False,
    }
    return render(request, "joatham_dashboard/expire.html", context)
