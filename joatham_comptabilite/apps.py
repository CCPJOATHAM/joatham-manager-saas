from django.apps import AppConfig


class JoathamComptabiliteConfig(AppConfig):
    name = 'joatham_comptabilite'

    def ready(self):
        import joatham_comptabilite.signals  # noqa: F401
