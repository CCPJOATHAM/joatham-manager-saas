# Captures du parcours d'abonnement

Rendus locaux avec données entièrement fictives, dans Edge. Aucun lien vers un prestataire n'a été suivi et aucun paiement n'a été lancé. La navigation et le forfait de la maquette sont simulés ; les tests HTTP/transactions sont exécutés séparément sur PostgreSQL en CI.

| Cas | FR ordinateur | FR mobile | EN ordinateur | EN mobile |
| --- | --- | --- | --- | --- |
| Avant : paiement en cours | [Avant FR](before-fr-desktop.jpg) | [Avant FR mobile](before-fr-mobile.jpg) | [Before EN](before-en-desktop.jpg) | [Before EN mobile](before-en-mobile.jpg) |
| Après : paiement en cours | [Après FR](pending-fr-desktop.jpg) | [Après FR mobile](pending-fr-mobile.jpg) | [After EN](pending-en-desktop.jpg) | [After EN mobile](pending-en-mobile.jpg) |
| Récapitulatif avant paiement | [FR](ready-fr-desktop.jpg) | [FR mobile](ready-fr-mobile.jpg) | [EN](ready-en-desktop.jpg) | [EN mobile](ready-en-mobile.jpg) |
| Confirmation après paiement | [FR](confirmed-fr-desktop.jpg) | [FR mobile](confirmed-fr-mobile.jpg) | [EN](confirmed-en-desktop.jpg) | [EN mobile](confirmed-en-mobile.jpg) |

42 vérifications automatiques : sept cas (avant, session à régler, en cours, confirmé, échoué, à vérifier, déclaration manuelle) × FR/EN × 1440/390/320 px. Contrôles de débordement et de montants invalides sur les nouveaux rendus ; absence du lien de paiement après confirmation ; textes anglais ; noms d'entreprise préservés. Le mode impression masque le menu et les commandes du compte et conserve les détails de paiement.

Le fichier `browser-checks.json` détaille les cas. Les captures sont cadrées sur le panneau concerné, sans modifier le menu global de l'application.
