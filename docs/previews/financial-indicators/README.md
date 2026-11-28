# Aperçus et contrôles — indicateurs financiers

Données entièrement fictives. Le scénario de janvier 2026 comprend une facture émise de 500 000 CDF, un paiement validé de 353 125 CDF, zéro facture entièrement soldée et un solde de 146 875 CDF. Des brouillons et annulations sont également présents pour vérifier leur exclusion du CA. Février contient une facture de 100 000 CDF réglée et un remboursement confirmé de 10 000 CDF : encaissement net de 90 000 CDF.

L'entreprise, `demo@example.invalid`, les documents et les paiements ont été créés uniquement dans un cluster PostgreSQL 14.24 temporaire sur localhost. Aucun accès à une base réelle, au VPS ou à un prestataire de paiement.

| Aperçu | Français | Anglais |
| --- | --- | --- |
| Période, devise et premiers indicateurs — ordinateur | [Voir](after-january-fr-desktop-overview.png) | [Voir](after-january-en-desktop-overview.png) |
| Indicateurs — ordinateur | [Voir](after-january-fr-desktop-kpis.png) | [Voir](after-january-en-desktop-kpis.png) |
| Explications ouvertes — ordinateur | [Voir](after-january-fr-desktop-definitions.png) | [Voir](after-january-en-desktop-definitions.png) |
| Tableau et barres mensuelles réelles — ordinateur | [Voir](after-january-fr-desktop-series.png) | [Voir](after-january-en-desktop-series.png) |
| Période — mobile | [Voir](after-january-fr-mobile-overview.png) | [Voir](after-january-en-mobile-overview.png) |
| Indicateurs — mobile | [Voir](after-january-fr-mobile-kpis.png) | [Voir](after-january-en-mobile-kpis.png) |
| Encaissements et explications — mobile | [Voir](after-january-fr-mobile-definitions.png) | [Voir](after-january-en-mobile-definitions.png) |
| Tableau mensuel — mobile | [Voir](after-january-fr-mobile-series.png) | [Voir](after-january-en-mobile-series.png) |

## Résultats locaux

- **967 tests Django, OK** en 314,545 s, sur PostgreSQL **14.24**, Python **3.14.10**, Django **6.0.10**. Les 13 nouveaux tests financiers sont inclus. Contrôle système sans anomalie.
- **9 tests JavaScript, OK**.
- **36 scénarios navigateur Edge, OK** : FR/EN, largeurs 1440/390/320 px, tout l'historique, janvier, février avec remboursement, période vide et dates invalides ; aucun débordement horizontal ni erreur JavaScript. Explications utilisables au clavier, cohérence des compteurs, montants et graphiques vérifiée.
- Domaines `django` et `djangojs` extraits/compilés et vérifiés par `check_translations --extract`. Les nouvelles traductions concernent le domaine Django ; aucune nouvelle chaîne JavaScript n'est nécessaire pour `Intl.NumberFormat`.
- `git diff --check` sans erreur.

Clarification du sous-titre du CA : le filtre reste `Facture.date` et la somme reste `Facture.montant` (HT avant remises). Le sous-titre et l'explication détaillée FR/EN précisent désormais la date d'enregistrement, sans ambiguïté avec la date des paiements. Après cette modification éditoriale, **13 tests financiers ciblés** ont été relancés sur PostgreSQL 14.24 : **OK**. Les catalogues sont régénérés et compilés ; la suite complète de 967 tests ci-dessus correspond à la version précédant cette seule clarification de texte.

Le scénario 353 125 / zéro facture soldée démontre un paiement partiel cohérent ; il ne constitue pas une inspection des données réelles de production. Les règles de reporting et les aperçus ont été validés pour publication d'une PR en brouillon. Consulter [le rapport d'audit et les limites des modèles](../../executive-financial-indicators-review.md). Aucune fusion ni aucun déploiement autorisé à ce stade.
