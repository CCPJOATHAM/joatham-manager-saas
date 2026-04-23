from django.db.models.signals import post_save
from django.dispatch import receiver

from joatham_depenses.models import Depense
from joatham_users.models import Entreprise

from .services.bootstrap import bootstrap_comptabilite_entreprise
from .services.comptabilisation import comptabiliser_depense


@receiver(post_save, sender=Entreprise)
def bootstrap_comptabilite_for_entreprise(sender, instance, created, **kwargs):
    if created:
        bootstrap_comptabilite_entreprise(instance)


@receiver(post_save, sender=Depense)
def comptabiliser_depense_a_la_creation(sender, instance, created, **kwargs):
    if created and instance.entreprise_id:
        comptabiliser_depense(instance)
