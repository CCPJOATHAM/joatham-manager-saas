"""Presentation of known system audit events; stored values and user text stay intact."""
import re

from django.utils.translation import gettext_lazy as _

MODULE_LABELS = {
    'apprenants': _('Apprenants'),
    'auth': _('Authentification'),
    'billing': _('Facturation'),
    'caisse': _('Caisse'),
    'clients': _('Clients'),
    'company': _('Entreprise'),
    'comptabilite': _('Comptabilité'),
    'depenses': _('Dépenses'),
    'messages': _('Messagerie'),
    'onboarding': _('Inscription entreprise'),
    'payments': _('Paiements'),
    'products': _('Produits'),
    'rh': _('Ressources humaines'),
    'services': _('Services'),
    'subscription': _('Abonnement'),
    'super_admin': _('Super admin'),
    'users': _('Utilisateurs'),
}

ACTION_LABELS = {
    'abonnement_active': _('Abonnement activé'),
    'abonnement_expire': _('Abonnement expiré'),
    'abonnement_plan_demande': _('Changement de plan demandé'),
    'abonnement_plan_demande_refusee': _('Changement de plan refusé'),
    'abonnement_plan_demande_validee': _('Changement de plan validé'),
    'abonnement_plan_modifie': _('Plan modifié'),
    'abonnement_suspendu': _('Abonnement suspendu'),
    'caisse_created': _('Caisse créée'),
    'caisse_deactivated': _('Caisse désactivée'),
    'caisse_movement_created': _('Mouvement de caisse créé'),
    'caisse_session_cancelled': _('Session de caisse annulée'),
    'caisse_session_closed': _('Session de caisse fermée'),
    'caisse_session_opened': _('Session de caisse ouverte'),
    'caisse_session_rejected': _('Session de caisse rejetée'),
    'caisse_session_validated': _('Session de caisse validée'),
    'caisse_updated': _('Caisse modifiée'),
    'client_cree': _('Client créé'),
    'creation_apprenant': _('Apprenant créé'),
    'depense_creee': _('Dépense créée'),
    'ecriture_comptable_creee': _('Écriture comptable créée'),
    'email_verification_sent': _('Email de confirmation envoyé'),
    'email_verified': _('Email confirmé'),
    'entreprise_creee': _('Entreprise créée'),
    'entreprise_desactivee': _('Entreprise désactivée'),
    'entreprise_modifiee': _('Entreprise modifiée'),
    'essai_prolonge': _('Essai prolongé'),
    'facture_creee': _('Facture créée'),
    'facture_deliee_inscription': _("Facture déliée de l'inscription"),
    'facture_existante_liee_inscription': _("Facture liée à l'inscription"),
    'facture_inscription_creee': _("Facture d'inscription créée"),
    'facture_payee': _('Paiement de facture enregistré'),
    'formation_creee': _('Formation créée'),
    'formation_modifiee': _('Formation modifiée'),
    'formation_statut_modifie': _('Statut de formation modifié'),
    'inscription_formation_creee': _('Inscription créée'),
    'inscription_montant_prevu_modifie': _("Montant de l'inscription modifié"),
    'inventory_session_created': _('Inventaire créé'),
    'inventory_session_validated': _('Inventaire validé'),
    'invitation_acceptee': _('Invitation acceptée'),
    'invitation_annulee': _('Invitation annulée'),
    'invitation_relance_envoyee': _("Rappel d'invitation envoyé"),
    'invitation_renvoyee': _('Invitation renvoyée'),
    'paiement_abonnement_cree': _("Paiement d'abonnement créé"),
    'paiement_abonnement_enregistre': _("Paiement d'abonnement enregistré"),
    'paiement_abonnement_refuse': _("Paiement d'abonnement refusé"),
    'paiement_abonnement_valide': _("Paiement d'abonnement validé"),
    'paiement_inscription_cree': _("Paiement d'inscription créé"),
    'password_reset_completed': _('Mot de passe réinitialisé'),
    'password_reset_requested': _('Réinitialisation du mot de passe demandée'),
    'plan_gratuit_active': _('Plan gratuit activé'),
    'previous_session_terminated_for_new_login': _('Ancienne session terminée'),
    'produit_cree': _('Produit créé'),
    'produit_modifie': _('Produit modifié'),
    'proforma_annulee': _('Proforma annulée'),
    'proforma_convertie': _('Proforma convertie'),
    'proforma_creee': _('Proforma créée'),
    'proforma_modifiee': _('Proforma modifiée'),
    'rh_avance_salaire_cancelled': _('Avance sur salaire annulée'),
    'rh_avance_salaire_created': _('Avance sur salaire créée'),
    'rh_conge_created': _('Congé demandé'),
    'rh_conge_decided': _('Décision de congé enregistrée'),
    'rh_document_created': _('Document RH créé'),
    'rh_employe_created': _('Employé créé'),
    'rh_employe_updated': _('Employé modifié'),
    'rh_paiement_salaire_created': _('Paiement de salaire créé'),
    'rh_poste_created': _('Poste RH créé'),
    'rh_presence_recorded': _('Présence enregistrée'),
    'service_cree': _('Service créé'),
    'service_modifie': _('Service modifié'),
    'service_statut_modifie': _('Statut de service modifié'),
    'session_conflict_cancelled': _('Nouvelle connexion annulée'),
    'session_conflict_detected': _('Conflit de session détecté'),
    'stock_movement_recorded': _('Mouvement de stock enregistré'),
    'subscription_auto_activated': _('Abonnement activé automatiquement'),
    'subscription_intent_created': _("Demande d'abonnement créée"),
    'subscription_payment_auto_confirmed': _('Paiement confirmé automatiquement'),
    'subscription_payment_auto_created': _('Paiement automatique créé'),
    'subscription_payment_auto_failed': _('Échec du paiement automatique'),
    'subscription_payment_webhook_duplicate': _('Notification de paiement dupliquée'),
    'subscription_payment_webhook_rejected': _('Notification de paiement rejetée'),
    'utilisateur_acces_retire': _('Accès utilisateur retiré'),
    'utilisateur_action_bloquee': _('Action utilisateur bloquée'),
    'utilisateur_cree': _('Utilisateur créé'),
    'utilisateur_desactive_historique': _('Utilisateur désactivé, historique conservé'),
    'utilisateur_invite': _('Utilisateur invité'),
    'utilisateur_modifie': _('Utilisateur modifié'),
    'utilisateur_statut_modifie': _('Statut utilisateur modifié'),
    'utilisateur_supprime': _('Utilisateur supprimé'),
}

DESCRIPTION_PATTERNS = {
    'abonnement_active': [
        (re.compile('Abonnement\\ active\\ sur\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Abonnement activé sur le plan %(value_1)s.')),
    ],
    'abonnement_expire': [
        (re.compile('Abonnement\\ expire\\ pour\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Abonnement expire pour le plan %(value_1)s.')),
    ],
    'abonnement_plan_demande': [
        (re.compile('Demande\\ de\\ plan\\ (?P<value_1>.*?)\\ envoyee\\.', re.DOTALL), _('Demande de plan %(value_1)s envoyée.')),
    ],
    'abonnement_plan_demande_refusee': [
        (re.compile('Demande\\ de\\ plan\\ (?P<value_1>.*?)\\ refusee\\.', re.DOTALL), _('Demande de plan %(value_1)s refusée.')),
    ],
    'abonnement_plan_demande_validee': [
        (re.compile('Demande\\ de\\ plan\\ (?P<value_1>.*?)\\ validee\\.', re.DOTALL), _('Demande de plan %(value_1)s validée.')),
    ],
    'abonnement_plan_modifie': [
        (re.compile('Plan\\ modifie\\ vers\\ (?P<value_1>.*?)\\ pour\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Plan modifié vers %(value_1)s pour %(value_2)s.')),
    ],
    'abonnement_suspendu': [
        (re.compile('Abonnement\\ suspendu\\ pour\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Abonnement suspendu pour le plan %(value_1)s.')),
    ],
    'caisse_created': [
        (re.compile('Caisse\\ creee\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Caisse créée : %(value_1)s.')),
    ],
    'caisse_deactivated': [
        (re.compile('Caisse\\ desactivee\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Caisse désactivée : %(value_1)s.')),
    ],
    'caisse_movement_created': [
        (re.compile('Mouvement\\ (?P<value_1>.*?)\\ enregistre\\ pour\\ la\\ caisse\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Mouvement %(value_1)s enregistré pour la caisse %(value_2)s.')),
    ],
    'caisse_session_cancelled': [
        (re.compile('Session\\ annulee\\ pour\\ la\\ caisse\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Session annulée pour la caisse %(value_1)s.')),
    ],
    'caisse_session_closed': [
        (re.compile('Session\\ fermee\\ pour\\ la\\ caisse\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Session fermée pour la caisse %(value_1)s.')),
    ],
    'caisse_session_opened': [
        (re.compile('Session\\ ouverte\\ pour\\ la\\ caisse\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Session ouverte pour la caisse %(value_1)s.')),
    ],
    'caisse_session_rejected': [
        (re.compile('Session\\ rejetee\\ pour\\ la\\ caisse\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Session rejetée pour la caisse %(value_1)s.')),
    ],
    'caisse_session_validated': [
        (re.compile('Session\\ validee\\ pour\\ la\\ caisse\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Session validée pour la caisse %(value_1)s.')),
    ],
    'caisse_updated': [
        (re.compile('Caisse\\ mise\\ a\\ jour\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Caisse mise à jour : %(value_1)s.')),
    ],
    'client_cree': [
        (re.compile('Client\\ cree:\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Client créé: %(value_1)s.')),
    ],
    'creation_apprenant': [
        (re.compile('Apprenant\\ cree:\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Apprenant créé: %(value_1)s.')),
    ],
    'depense_creee': [
        (re.compile('Depense\\ creee:\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Dépense créée: %(value_1)s.')),
    ],
    'ecriture_comptable_creee': [
        (re.compile('Ecriture\\ comptable\\ creee:\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Écriture comptable créée: %(value_1)s.')),
    ],
    'email_verification_sent': [
        (re.compile('Email\\ de\\ confirmation\\ envoye\\ a\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Email de confirmation envoyé à %(value_1)s.')),
    ],
    'email_verified': [
        (re.compile('Adresse\\ email\\ confirmee\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Adresse email confirmée pour %(value_1)s.')),
    ],
    'entreprise_creee': [
        (re.compile('Entreprise\\ creee\\ depuis\\ le\\ parcours\\ SaaS:\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Entreprise créée depuis le parcours SaaS: %(value_1)s.')),
    ],
    'entreprise_desactivee': [
        (re.compile('Entreprise\\ desactivee\\ par\\ super\\ admin\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Entreprise désactivée par super admin : %(value_1)s.')),
    ],
    'entreprise_modifiee': [
        (re.compile("Parametres\\ de\\ l'entreprise\\ mis\\ a\\ jour\\ pour\\ (?P<value_1>.*?)\\.", re.DOTALL), _("Paramètres de l'entreprise mis à jour pour %(value_1)s.")),
    ],
    'essai_prolonge': [
        (re.compile('Acces\\ historique\\ prolonge\\ de\\ (?P<value_1>.*?)\\ jour\\(s\\)\\ pour\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Accès historique prolongé de %(value_1)s jour(s) pour %(value_2)s.')),
        (re.compile('Ancien\\ essai\\ prolonge\\ sur\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Ancien essai prolongé sur le plan %(value_1)s.')),
    ],
    'facture_creee': [
        (re.compile('Facture\\ (?P<value_1>.*?)\\ creee\\ pour\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Facture %(value_1)s créée pour %(value_2)s.')),
    ],
    'facture_deliee_inscription': [
        (re.compile("Facture\\ (?P<value_1>.*?)\\ deliee\\ de\\ l'inscription\\ (?P<value_2>.*?)\\.", re.DOTALL), _("Facture %(value_1)s déliée de l'inscription %(value_2)s.")),
    ],
    'facture_existante_liee_inscription': [
        (re.compile("Facture\\ existante\\ (?P<value_1>.*?)\\ liee\\ a\\ l'inscription\\ (?P<value_2>.*?)\\.", re.DOTALL), _("Facture existante %(value_1)s liée à l'inscription %(value_2)s.")),
    ],
    'facture_inscription_creee': [
        (re.compile("Facture\\ (?P<value_1>.*?)\\ creee\\ pour\\ l'inscription\\ (?P<value_2>.*?)\\.", re.DOTALL), _("Facture %(value_1)s créée pour l'inscription %(value_2)s.")),
    ],
    'facture_payee': [
        (re.compile('Paiement\\ enregistre\\ sur\\ la\\ facture\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Paiement enregistré sur la facture %(value_1)s.')),
    ],
    'formation_creee': [
        (re.compile('Formation\\ creee:\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Formation créée: %(value_1)s.')),
    ],
    'formation_modifiee': [
        (re.compile('Formation\\ modifiee:\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Formation modifiée: %(value_1)s.')),
    ],
    'formation_statut_modifie': [
        (re.compile('Formation\\ (?P<value_1>.*?):\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Formation %(value_1)s: %(value_2)s.')),
    ],
    'inscription_formation_creee': [
        (re.compile('Inscription\\ creee\\ pour\\ (?P<value_1>.*?)\\ a\\ la\\ formation\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Inscription créée pour %(value_1)s à la formation %(value_2)s.')),
    ],
    'inscription_montant_prevu_modifie': [
        (re.compile("Montant\\ prévu\\ modifié\\ pour\\ l'inscription\\ (?P<value_1>.*?)\\.", re.DOTALL), _("Montant prévu modifié pour l'inscription %(value_1)s.")),
    ],
    'inventory_session_created': [
        (re.compile("Session\\ d'inventaire\\ creee\\ :\\ (?P<value_1>.*?)\\.", re.DOTALL), _("Session d'inventaire créée : %(value_1)s.")),
    ],
    'inventory_session_validated': [
        (re.compile("Session\\ d'inventaire\\ validee\\ :\\ (?P<value_1>.*?)\\.", re.DOTALL), _("Session d'inventaire validée : %(value_1)s.")),
    ],
    'invitation_acceptee': [
        (re.compile('Invitation\\ acceptee\\ par\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Invitation acceptée par %(value_1)s.')),
    ],
    'invitation_annulee': [
        (re.compile('Invitation\\ annulee\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Invitation annulée pour %(value_1)s.')),
    ],
    'invitation_relance_envoyee': [
        (re.compile("Relance\\ envoyee\\ pour\\ l'invitation\\ (?P<value_1>.*?)\\.", re.DOTALL), _("Relance envoyée pour l'invitation %(value_1)s.")),
    ],
    'invitation_renvoyee': [
        (re.compile('Invitation\\ renvoyee\\ a\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Invitation renvoyée à %(value_1)s.')),
    ],
    'paiement_abonnement_cree': [
        (re.compile('Demande\\ de\\ paiement\\ abonnement\\ creee\\ pour\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Demande de paiement abonnement créée pour le plan %(value_1)s.')),
    ],
    'paiement_abonnement_enregistre': [
        (re.compile('Paiement\\ manuel\\ enregistre\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Paiement manuel enregistré pour %(value_1)s.')),
    ],
    'paiement_abonnement_refuse': [
        (re.compile('Paiement\\ abonnement\\ refuse\\ pour\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Paiement abonnement refusé pour le plan %(value_1)s.')),
    ],
    'paiement_abonnement_valide': [
        (re.compile('Paiement\\ abonnement\\ valide\\ pour\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Paiement abonnement validé pour le plan %(value_1)s.')),
    ],
    'paiement_inscription_cree': [
        (re.compile('Paiement\\ enregistre\\ pour\\ (?P<value_1>.*?)\\ sur\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Paiement enregistré pour %(value_1)s sur %(value_2)s.')),
    ],
    'password_reset_completed': [
        (re.compile('Mot\\ de\\ passe\\ réinitialisé\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Mot de passe réinitialisé pour %(value_1)s.')),
    ],
    'password_reset_requested': [
        (re.compile('Demande\\ de\\ réinitialisation\\ du\\ mot\\ de\\ passe\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Demande de réinitialisation du mot de passe pour %(value_1)s.')),
    ],
    'plan_gratuit_active': [
        (re.compile('Plan\\ gratuit\\ active\\ sur\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Plan gratuit activé sur %(value_1)s.')),
    ],
    'previous_session_terminated_for_new_login': [
        (re.compile('Session\\ precedente\\ terminee\\ pour\\ connecter\\ (?P<value_1>.*?)\\ sur\\ un\\ nouvel\\ appareil\\.', re.DOTALL), _('Session précédente terminée pour connecter %(value_1)s sur un nouvel appareil.')),
    ],
    'produit_cree': [
        (re.compile('Produit\\ cree\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Produit créé : %(value_1)s.')),
    ],
    'produit_modifie': [
        (re.compile('Produit\\ modifie\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Produit modifié : %(value_1)s.')),
    ],
    'proforma_annulee': [
        (re.compile('Proforma\\ (?P<value_1>.*?)\\ annulee\\.', re.DOTALL), _('Proforma %(value_1)s annulée.')),
    ],
    'proforma_convertie': [
        (re.compile('Proforma\\ (?P<value_1>.*?)\\ convertie\\ en\\ facture\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Proforma %(value_1)s convertie en facture %(value_2)s.')),
    ],
    'proforma_creee': [
        (re.compile('Proforma\\ (?P<value_1>.*?)\\ creee\\ pour\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Proforma %(value_1)s créée pour %(value_2)s.')),
    ],
    'proforma_modifiee': [
        (re.compile('Proforma\\ (?P<value_1>.*?)\\ modifiee\\.', re.DOTALL), _('Proforma %(value_1)s modifiée.')),
    ],
    'rh_avance_salaire_cancelled': [
        (re.compile('Avance\\ sur\\ salaire\\ annulee\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Avance sur salaire annulée pour %(value_1)s.')),
    ],
    'rh_avance_salaire_created': [
        (re.compile('Avance\\ sur\\ salaire\\ creee\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Avance sur salaire créée pour %(value_1)s.')),
    ],
    'rh_conge_created': [
        (re.compile('Demande\\ de\\ conge\\ creee\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Demande de congé créée pour %(value_1)s.')),
    ],
    'rh_conge_decided': [
        (re.compile('Demande\\ de\\ conge\\ (?P<value_1>.*?)\\ pour\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Demande de congé %(value_1)s pour %(value_2)s.')),
    ],
    'rh_document_created': [
        (re.compile('Document\\ RH\\ cree\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Document RH créé : %(value_1)s.')),
    ],
    'rh_employe_created': [
        (re.compile('Employe\\ RH\\ cree\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Employé RH créé : %(value_1)s.')),
    ],
    'rh_employe_updated': [
        (re.compile('Employe\\ RH\\ modifie\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Employé RH modifié : %(value_1)s.')),
    ],
    'rh_paiement_salaire_created': [
        (re.compile('Paiement\\ salaire\\ cree\\ pour\\ (?P<value_1>.*?)\\ \\-\\ (?P<value_2>.*?)/(?P<value_3>.*?)\\.', re.DOTALL), _('Paiement salaire créé pour %(value_1)s - %(value_2)s/%(value_3)s.')),
    ],
    'rh_poste_created': [
        (re.compile('Poste\\ RH\\ cree\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Poste RH créé : %(value_1)s.')),
    ],
    'rh_presence_recorded': [
        (re.compile('Presence\\ RH\\ enregistree\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Présence RH enregistrée pour %(value_1)s.')),
    ],
    'service_cree': [
        (re.compile('Service\\ créé\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Service créé : %(value_1)s.')),
    ],
    'service_modifie': [
        (re.compile('Service\\ modifié\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Service modifié : %(value_1)s.')),
    ],
    'service_statut_modifie': [
        (re.compile('Statut\\ du\\ service\\ modifié\\ :\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Statut du service modifié : %(value_1)s.')),
    ],
    'session_conflict_cancelled': [
        (re.compile('Conflit\\ de\\ session\\ annule\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Conflit de session annulé pour %(value_1)s.')),
    ],
    'session_conflict_detected': [
        (re.compile('Conflit\\ de\\ session\\ detecte\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Conflit de session détecté pour %(value_1)s.')),
    ],
    'subscription_auto_activated': [
        (re.compile('Abonnement\\ active\\ automatiquement\\ sur\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Abonnement activé automatiquement sur le plan %(value_1)s.')),
    ],
    'subscription_intent_created': [
        (re.compile('Intention\\ abonnement\\ creee\\ pour\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Intention abonnement créée pour le plan %(value_1)s.')),
    ],
    'subscription_payment_auto_confirmed': [
        (re.compile('Paiement\\ automatique\\ confirme\\ pour\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Paiement automatique confirmé pour le plan %(value_1)s.')),
    ],
    'subscription_payment_auto_created': [
        (re.compile('Paiement\\ automatique\\ cree\\ pour\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Paiement automatique créé pour le plan %(value_1)s.')),
    ],
    'subscription_payment_auto_failed': [
        (re.compile('Paiement\\ automatique\\ echoue\\ pour\\ le\\ plan\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Paiement automatique échoué pour le plan %(value_1)s.')),
    ],
    'subscription_payment_webhook_duplicate': [
        (re.compile('Webhook\\ paiement\\ abonnement\\ deja\\ traite\\.', re.DOTALL), _('Webhook paiement abonnement déjà traite.')),
    ],
    'subscription_payment_webhook_rejected': [
        (re.compile('Webhook\\ paiement\\ abonnement\\ rejete\\ apres\\ verification\\.', re.DOTALL), _('Webhook paiement abonnement rejeté après vérification.')),
        (re.compile('Webhook\\ paiement\\ abonnement\\ rejete\\ avant\\ identification\\.', re.DOTALL), _('Webhook paiement abonnement rejeté avant identification.')),
        (re.compile('Webhook\\ paiement\\ abonnement\\ rejete\\ pour\\ reference\\ inconnue\\.', re.DOTALL), _('Webhook paiement abonnement rejeté pour référence inconnue.')),
    ],
    'utilisateur_acces_retire': [
        (re.compile('Acces\\ retire\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Accès retire pour %(value_1)s.')),
    ],
    'utilisateur_cree': [
        (re.compile('Compte\\ proprietaire\\ cree\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Compte propriétaire créé pour %(value_1)s.')),
        (re.compile('Utilisateur\\ (?P<value_1>.*?)\\ cree\\ avec\\ le\\ role\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Utilisateur %(value_1)s créé avec le rôle %(value_2)s.')),
    ],
    'utilisateur_desactive_historique': [
        (re.compile('Utilisateur\\ (?P<value_1>.*?)\\ desactive\\ afin\\ de\\ preserver\\ la\\ tracabilite\\.', re.DOTALL), _('Utilisateur %(value_1)s désactivé afin de préserver la traçabilité.')),
    ],
    'utilisateur_invite': [
        (re.compile('Invitation\\ envoyee\\ a\\ (?P<value_1>.*?)\\ pour\\ le\\ role\\ (?P<value_2>.*?)\\.', re.DOTALL), _('Invitation envoyée à %(value_1)s pour le rôle %(value_2)s.')),
    ],
    'utilisateur_modifie': [
        (re.compile('Utilisateur\\ (?P<value_1>.*?)\\ modifie\\.', re.DOTALL), _('Utilisateur %(value_1)s modifié.')),
    ],
    'utilisateur_statut_modifie': [
        (re.compile('Statut\\ utilisateur\\ mis\\ a\\ jour\\ pour\\ (?P<value_1>.*?)\\.', re.DOTALL), _('Statut utilisateur mis à jour pour %(value_1)s.')),
    ],
    'utilisateur_supprime': [
        (re.compile('Utilisateur\\ (?P<value_1>.*?)\\ supprime\\.', re.DOTALL), _('Utilisateur %(value_1)s supprimé.')),
    ],
}


def module_label(value):
    return str(MODULE_LABELS.get(value, value))


def action_label(value):
    return str(ACTION_LABELS.get(value, value))


def description_label(log):
    for pattern, message in DESCRIPTION_PATTERNS.get(log.action, ()):
        match = pattern.fullmatch(log.description)
        if match:
            return str(message) % match.groupdict()
    return log.description


def invoice_history_description(event):
    # Notes entered by a user fall through unchanged.
    action = {"creation": "facture_creee", "paiement": "facture_payee"}.get(event.action)
    for pattern, message in DESCRIPTION_PATTERNS.get(action, ()):
        match = pattern.fullmatch(event.description)
        if match:
            return str(message) % match.groupdict()
    if event.action == "modification":
        match = re.fullmatch(r"Facture (.*?) modifiee\.", event.description, re.DOTALL)
        if match:
            return _('Facture %(number)s modifiée.') % {"number": match.group(1)}
    return event.description
