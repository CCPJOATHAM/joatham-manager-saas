from django.core.management.base import BaseCommand

from joatham_users.models import Abonnement


DEFAULT_PLANS = [
    {
        "code": "starter",
        "nom": "Starter",
        "prix": 19,
        "prix_annuel": 190,
        "devise": "USD",
        "duree_jours": 30,
        "description": "L'essentiel pour demarrer avec la gestion commerciale JOATHAM Manager.",
        "modules_inclus": ["dashboard", "clients", "factures", "services"],
        "max_utilisateurs": 3,
        "max_factures_mois": 100,
        "max_clients": 200,
        "max_apprenants": 0,
        "acces_comptabilite": False,
        "acces_exports": True,
    },
    {
        "code": "pro",
        "nom": "Pro",
        "prix": 49,
        "prix_annuel": 490,
        "devise": "USD",
        "duree_jours": 30,
        "description": "Le plan complet pour piloter ventes, depenses, comptabilite et equipe.",
        "modules_inclus": ["dashboard", "clients", "factures", "services", "depenses", "comptabilite", "utilisateurs"],
        "max_utilisateurs": 10,
        "max_factures_mois": 500,
        "max_clients": 1000,
        "max_apprenants": 0,
        "acces_comptabilite": True,
        "acces_exports": True,
    },
    {
        "code": "premium",
        "nom": "Premium",
        "prix": 99,
        "prix_annuel": 990,
        "devise": "USD",
        "duree_jours": 30,
        "description": "Pour les organisations qui veulent tous les modules et des capacites etendues.",
        "modules_inclus": ["dashboard", "clients", "factures", "services", "depenses", "comptabilite", "apprenants", "utilisateurs"],
        "max_utilisateurs": None,
        "max_factures_mois": None,
        "max_clients": None,
        "max_apprenants": None,
        "acces_comptabilite": True,
        "acces_exports": True,
    },
]


class Command(BaseCommand):
    help = "Cree ou met a jour les plans SaaS payants par defaut sans toucher au plan d'essai."

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for payload in DEFAULT_PLANS:
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

        self.stdout.write(self.style.SUCCESS(f"Plans SaaS traites : {created} cree(s), {updated} mis a jour."))
