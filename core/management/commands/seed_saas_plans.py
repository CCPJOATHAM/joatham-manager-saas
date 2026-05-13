from django.core.management.base import BaseCommand

from core.services.subscription import deactivate_legacy_trial_plans, get_default_paid_plans, get_or_create_free_plan
from joatham_users.models import Abonnement


class Command(BaseCommand):
    help = "Cree ou met a jour les plans SaaS par defaut, dont le plan gratuit freemium."

    def handle(self, *args, **options):
        created = 0
        updated = 0
        free_plan = get_or_create_free_plan()
        self.stdout.write(f"{free_plan.nom} pret.")
        legacy_count = deactivate_legacy_trial_plans()
        for payload in get_default_paid_plans():
            plan = Abonnement.objects.filter(code=payload["code"]).order_by("id").first()
            if plan is None:
                plan = Abonnement.objects.filter(nom__iexact=payload["nom"]).order_by("id").first()

            defaults = {**payload, "actif": True}
            if plan is None:
                plan = Abonnement.objects.create(**defaults)
                created += 1
            else:
                for field, value in defaults.items():
                    setattr(plan, field, value)
                plan.save(update_fields=list(defaults.keys()))
                updated += 1
            self.stdout.write(f"{plan.nom} pret.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Plans SaaS traites : {created} cree(s), {updated} mis a jour, {legacy_count} essai(s) legacy desactive(s)."
            )
        )
