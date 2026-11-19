# Relecture prioritaire des traductions financières et des emails

Liste courte pour la revue de la PR #31. La colonne anglaise présente le texte corrigé dans le catalogue. Les formulations françaises ci-dessous reprennent les clés sources ; leurs accents historiques ne sont pas modifiés par ce correctif.

| Zone | Français | Anglais corrigé |
| --- | --- | --- |
| Factures | %(count)s facture non soldee | %(count)s outstanding invoice |
| Factures | Montant encaisse | Amount received |
| Paiements | Seuls les paiements en attente peuvent etre valides. | Only pending payments can be approved. |
| Paiements | Enregistrer le paiement | Record payment |
| Abonnements | Demande de paiement | Payment request |
| Abonnements | Réactiver l'abonnement | Reactivate subscription |
| Emails | Votre acces JOATHAM Manager est pret | Your JOATHAM Manager account is ready |
| Emails | . Si le delai est depasse, demandez une nouvelle invitation. | . If the link has expired, request a new invitation. |
| PDF | Ticket de caisse | Sales receipt |
| PDF | Quittance de paiement | Payment receipt |
| PDF | Total a payer | Total amount due |
| PDF | Ce document est une facture proforma et ne constitue pas une facture definitive. | This document is a pro forma invoice, not a final invoice. |

Points de validation métier : le solde non réglé reste bien dû ; une approbation manuelle est distinguée d’une confirmation de paiement ; une proforma reste un document provisoire. Les pluriels conservent le sens à 1 comme à plusieurs éléments.

Les noms d’entreprises, personnes, contenus saisis, références, montants, monnaies, paramètres et liens ne sont pas modifiés. Les catalogues français restent inchangés. Les corrections anglaises complètes sont visibles dans le diff de locale/en/LC_MESSAGES/django.po.
