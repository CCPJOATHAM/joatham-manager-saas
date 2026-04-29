from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from .models import PublicQuestion, SuggestionSuperAdmin


User = get_user_model()


class ConversationCreateForm(forms.Form):
    sujet = forms.CharField(max_length=180, label=_("Sujet"))
    participants = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        label=_("Participants"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    contenu = forms.CharField(
        label=_("Message"),
        widget=forms.Textarea(attrs={"rows": 6}),
    )

    def __init__(self, *args, entreprise=None, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.entreprise = entreprise
        self.current_user = current_user
        users = User.objects.none()
        if entreprise is not None:
            users = User.objects.filter(entreprise=entreprise, is_active=True).order_by(
                "first_name",
                "last_name",
                "username",
            )
            if current_user is not None:
                users = users.exclude(id=current_user.id)
        self.fields["participants"].queryset = users
        self.fields["sujet"].widget.attrs.update({"placeholder": _("Sujet de la conversation")})
        self.fields["contenu"].widget.attrs.update({"placeholder": _("Votre message")})


class MessageReplyForm(forms.Form):
    contenu = forms.CharField(
        label=_("Message"),
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": _("Ecrire une reponse")}),
    )


class SuggestionSuperAdminForm(forms.ModelForm):
    class Meta:
        model = SuggestionSuperAdmin
        fields = ["sujet", "message"]
        labels = {
            "sujet": _("Sujet"),
            "message": _("Suggestion"),
        }
        widgets = {
            "sujet": forms.TextInput(attrs={"placeholder": _("Ex. amelioration du module facturation")}),
            "message": forms.Textarea(attrs={"rows": 6, "placeholder": _("Decrivez votre besoin ou votre suggestion")}),
        }


class PublicQuestionForm(forms.ModelForm):
    class Meta:
        model = PublicQuestion
        fields = ["nom", "email", "telephone", "sujet", "message"]
        labels = {
            "nom": _("Nom"),
            "email": _("E-mail"),
            "telephone": _("Telephone"),
            "sujet": _("Sujet"),
            "message": _("Message"),
        }
        widgets = {
            "nom": forms.TextInput(attrs={"placeholder": _("Votre nom")}),
            "email": forms.EmailInput(attrs={"placeholder": "adresse@example.com"}),
            "telephone": forms.TextInput(attrs={"placeholder": "+243..."}),
            "sujet": forms.TextInput(attrs={"placeholder": _("Votre question")}),
            "message": forms.Textarea(attrs={"rows": 6, "placeholder": _("Votre message")}),
        }
