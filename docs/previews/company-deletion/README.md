# Aperçus de la demande de suppression

Données et compteurs entièrement fictifs ; rendu du template Django sans accès à une base. Aucun formulaire n'a été soumis. Les captures sont cadrées sur le panneau de revue.

| État | FR ordinateur | FR téléphone | EN ordinateur | EN téléphone |
| --- | --- | --- | --- | --- |
| Avant confirmation | [Voir](ready-fr-desktop.jpg) | [Voir](ready-fr-mobile.jpg) | [Voir](ready-en-desktop.jpg) | [Voir](ready-en-mobile.jpg) |
| Demande programmée | [Voir](pending-fr-desktop.jpg) | [Voir](pending-fr-mobile.jpg) | [Voir](pending-en-desktop.jpg) | [Voir](pending-en-mobile.jpg) |
| Après 30 jours, purge toujours gelée | [Voir](expired-fr-desktop.jpg) | [Voir](expired-fr-mobile.jpg) | [Voir](expired-en-desktop.jpg) | [Voir](expired-en-mobile.jpg) |
| Demande annulée | [Voir](cancelled-fr-desktop.jpg) | [Voir](cancelled-fr-mobile.jpg) | [Voir](cancelled-en-desktop.jpg) | [Voir](cancelled-en-mobile.jpg) |

30 contrôles Edge : cinq états (dont nom invalide), deux langues et trois largeurs (1440, 390 et 320 px). Vérifications de débordement, champs requis et étiquetés, indication d'erreur, POST et jeton CSRF, export disponible, annulation pendant le gel et absence de commande de purge irréversible. Détail : `browser-checks.json`.
