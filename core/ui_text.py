from django.utils.translation import gettext_lazy as _


FLASH_MESSAGES = {
    "company_updated": _("Les coordonnees de l'entreprise ont ete mises a jour."),
    "already_logged_in": _("Vous etes deja connecte. Deconnectez-vous pour acceder a cette page."),
    "signup_success": _("Votre entreprise a ete creee avec succes. Le plan gratuit a ete active."),
    "logged_out": _("Vous avez ete deconnecte. Vous pouvez maintenant vous connecter ou creer votre entreprise."),
    "invoice_created": _("La facture a ete creee avec succes."),
    "invoice_updated": _("La facture a ete modifiee avec succes."),
    "invoice_status_updated": _("Le statut de la facture a ete mis a jour."),
    "invoice_payment_created": _("Le paiement a ete enregistre."),
    "invoice_payment_quick": _("Le paiement complet a ete enregistre."),
    "user_created": _("L'utilisateur a ete cree avec succes."),
    "user_updated": _("L'utilisateur a ete mis a jour avec succes."),
    "user_deleted": _("L'utilisateur a ete supprime avec succes."),
}


TERMS = {
    "client": _("Client"),
    "expense": _("Depense"),
    "invoice": _("Facture"),
    "user": _("Utilisateur"),
    "learner": _("Apprenant"),
}
