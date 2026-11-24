import json
from django.core.management.base import BaseCommand, CommandError
from core.services.company_deletion import build_purge_plan, purge_company, require_super_admin, DeletionWorkflowError
from django.core.exceptions import PermissionDenied
from joatham_users.models import Entreprise, User


class Command(BaseCommand):
    help = "Simulate company purge; irreversible execution remains blocked pending retention approval."

    def add_arguments(self, parser):
        parser.add_argument("company_id", type=int)
        parser.add_argument("--actor-id", type=int, required=True)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--simulate", action="store_true")
        mode.add_argument("--execute", action="store_true")
        parser.add_argument("--confirmation-name", default="")
        parser.add_argument("--reason", default="")
        parser.add_argument("--plan-hash", default="")
        parser.add_argument("--retention-review", default="")

    def handle(self, *args, **options):
        try:
            actor = require_super_admin(User.objects.get(pk=options["actor_id"]))
            company = Entreprise.objects.get(pk=options["company_id"])
            if options["execute"]:
                purge_company(company_id=company.pk, actor=actor, confirmation_name=options["confirmation_name"],
                              reason=options["reason"], plan_hash=options["plan_hash"], retention_review=options["retention_review"])
            else:
                plan, _ = build_purge_plan(company)
                self.stdout.write(json.dumps({"mode": "simulation_only", **plan}, ensure_ascii=False, sort_keys=True, indent=2))
        except (User.DoesNotExist, Entreprise.DoesNotExist, PermissionDenied, DeletionWorkflowError) as error:
            raise CommandError(str(error)) from error
