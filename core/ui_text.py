from django.utils.translation import gettext_lazy as _


FLASH_MESSAGES = {
    "company_updated": _("Les coordonnées de l'entreprise ont été mises à jour."),
    "already_logged_in": _('Vous êtes déjà connecté. Déconnectez-vous pour accéder à cette page.'),
    "signup_success": _('Votre entreprise a été créée avec succès. Le plan gratuit a été activé.'),
    "logged_out": _('Vous avez été déconnecté. Vous pouvez maintenant vous connecter ou créer votre entreprise.'),
    "invoice_created": _('La facture a été créée avec succès.'),
    "invoice_updated": _('La facture a été modifiée avec succès.'),
    "invoice_status_updated": _('Le statut de la facture a été mis à jour.'),
    "invoice_payment_created": _('Le paiement a été enregistré.'),
    "invoice_payment_quick": _('Le paiement complet a été enregistré.'),
    "user_created": _("L'utilisateur a été créé avec succès."),
    "user_updated": _("L'utilisateur a été mis à jour avec succès."),
    "user_deleted": _("L'utilisateur a été supprimé avec succès."),
    "user_deactivated_history": _(
        "Cet utilisateur possède déjà un historique. Il a été désactivé afin de préserver la traçabilité."
    ),
}


TERMS = {
    "client": _("Client"),
    "expense": _('Dépense'),
    "invoice": _("Facture"),
    "user": _("Utilisateur"),
    "learner": _("Apprenant"),
}
