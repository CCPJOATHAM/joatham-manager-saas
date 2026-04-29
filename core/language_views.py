from django.utils import translation
from django.views.decorators.http import require_POST
from django.views.i18n import set_language as django_set_language

from core.services.language import persist_language_preference


@require_POST
def set_language_preference(request):
    language_code = persist_language_preference(request, request.POST.get("language"))
    if language_code:
        translation.activate(language_code)
        request.LANGUAGE_CODE = language_code

    return django_set_language(request)
