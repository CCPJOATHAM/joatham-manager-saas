# Relecture prioritaire des traductions financières et des emails

Liste courte pour la revue de la PR #31. La colonne anglaise présente le texte corrigé dans le catalogue. Les formulations françaises ci-dessous sont désormais corrigées dans les sources et les catalogues. Les traductions anglaises relues sont conservées lors de la régénération FR/EN.

| Zone | Français | Anglais corrigé |
| --- | --- | --- |
| Factures | %(count)s facture non soldée | %(count)s outstanding invoice |
| Factures | Montant encaissé | Amount received |
| Paiements | Seuls les paiements en attente peuvent être validés. | Only pending payments can be approved. |
| Paiements | Enregistrer le paiement | Record payment |
| Abonnements | Demande de paiement | Payment request |
| Abonnements | Réactiver l'abonnement | Reactivate subscription |
| Emails | Votre accès JOATHAM Manager est prêt | Your JOATHAM Manager account is ready |
| Emails | . Si le délai est dépassé, demandez une nouvelle invitation. | . If the link has expired, request a new invitation. |
| PDF | Ticket de caisse | Sales receipt |
| PDF | Quittance de paiement | Payment receipt |
| PDF | Total à payer | Total amount due |
| PDF | Ce document est une facture proforma et ne constitue pas une facture définitive. | This document is a pro forma invoice, not a final invoice. |

Points de validation métier : le solde non réglé reste bien dû ; une approbation manuelle est distinguée d’une confirmation de paiement ; une proforma reste un document provisoire. Les pluriels conservent le sens à 1 comme à plusieurs éléments.

Les noms d’entreprises, personnes, contenus saisis, références, montants, monnaies, paramètres et liens ne sont pas modifiés. Les catalogues français sont corrigés et recompilés ; les contenus saisis ne subissent aucune correction automatique. Les corrections anglaises complètes sont visibles dans le diff de locale/en/LC_MESSAGES/django.po.

## Accents et orthographe français

Les corrections couvrent les templates, messages Python, formulaires, confirmations JavaScript, emails et PDF : « montant encaissé », « facture non soldée / factures non soldées », « à », « être », « validés », « accès », « prêt », « référence », « rôle », « période » et les autres libellés relus.

Les choix et identifiants techniques des modèles, les migrations et les motifs reconnaissant les anciens journaux sont conservés. Les libellés historiques sont corrigés à l’affichage par le catalogue français. Aucune réécriture des données enregistrées ni aucun changement de schéma n’est nécessaire.

Les tests ciblés vérifient les pluriels et libellés de factures, une validation Python FR/EN, le catalogue JavaScript, les emails et le texte extrait des PDF. Un nom de client volontairement saisi « Montant encaisse » doit rester inchangé alors que le libellé de l’interface affiche « Montant encaissé ».
