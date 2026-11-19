from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from core.i18n_audit import catalog_state, catalog_errors, python_errors, template_errors


class Command(BaseCommand):
    help = "Check complete FR/EN catalogs and translatable template labels."

    def add_arguments(self, parser):
        parser.add_argument("--extract", action="store_true", help="Also check that source extraction matches committed catalogs (requires gettext).")

    def handle(self, *args, **options):
        if options["extract"]:
            paths = [settings.BASE_DIR / "locale" / language / "LC_MESSAGES" / (domain + ".po")
                     for language in ("fr", "en") for domain in ("django", "djangojs")]
            original = {path: path.read_bytes() for path in paths}
            before = {path: catalog_state(path) for path in paths}
            try:
                for domain in ("django", "djangojs"):
                    call_command("makemessages", locale=["fr", "en"], domain=domain,
                                 no_wrap=True, no_location=True, no_obsolete=True,
                                 ignore_patterns=[".venv", "env", ".git", "test_project", "test*.py"],
                                 verbosity=0)
                stale = [str(path.relative_to(settings.BASE_DIR)) for path in paths
                         if catalog_state(path) != before[path]]
            finally:
                for path, content in original.items():
                    path.write_bytes(content)
            if stale:
                raise CommandError("Catalogs need extraction/update: " + ", ".join(stale))
        errors = catalog_errors() + template_errors() + python_errors()
        if errors:
            raise CommandError("\n".join(errors))
        self.stdout.write(self.style.SUCCESS("FR/EN catalogs and templates verified."))
