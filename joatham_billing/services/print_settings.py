from ..models import EntreprisePrintSettings


def get_or_create_print_settings(entreprise):
    settings, _ = EntreprisePrintSettings.objects.get_or_create(entreprise=entreprise)
    return settings
