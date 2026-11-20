# Facturation, profil, conversion et navigation

Branche issue de `main` à la révision `65d0995`. Aucune migration ni modification de tarification.

## Causes reproduites et corrections

| Problème | Cause | Correction |
|---|---|---|
| Prévisualisation à zéro | Une devise historique `FC` arrive dans `Intl.NumberFormat`, qui exige un code ISO : `RangeError: Invalid currency code : FC`. Le calcul s'arrête avant de renseigner les totaux. En FR, les prix de catalogue et certaines valeurs de TVA sont aussi localisés avec une virgule dans des attributs numériques. | Normalisation de lecture `FC → CDF`, `FCFA → XAF`, valeurs numériques non localisées, formatage tolérant aux anciennes valeurs inconnues. Les deux éditeurs utilisent le même calcul exact en centimes et points de pourcentage ; les modifications de quantité, prix, TVA et réductions recalculent les lignes et les totaux. |
| Pays en texte libre | Le formulaire attribuait `.choices` à un `CharField` dont le widget restait `TextInput`. La devise était également un champ libre. | Deux vrais `ChoiceField` réutilisent les listes de création d'entreprise. Le pays actuel est sélectionné ; une ancienne valeur hors liste reste disponible pour ne pas effacer une donnée existante. Les nouvelles valeurs inconnues sont rejetées. |
| `None FC` et taux `None` | Les libellés non ISO empêchent de trouver un taux normal ; l'absence de taux est légitime mais l'aperçu HTML l'affiche sans garde et la matrice JavaScript transforme `None` en chaîne. | Codes ISO au moment de la conversion, réutilisation des anciens taux manuels équivalents sans réécriture de l'historique, valeurs JSON `null`, état traduit « Conversion temporairement indisponible. » et tiret pour le taux. Les taux nuls, négatifs ou non finis sont rejetés/ignorés ; aucun taux n'est inventé. |
| Audit absent pour le comptable | La permission existante `audit.view` autorise le comptable et la vue applique l'accès au module, mais le menu imposait en plus le rôle propriétaire. | Ajout du comptable à cette entrée, sans toucher à la permission, à la politique des plans ni au filtrage par entreprise de la vue. |

`FCFA` correspond à `XAF` dans les libellés existants du projet. `XOF` reste un code distinct, avec son propre taux. Les alias sont interprétés à la lecture : les montants et anciennes devises/taux enregistrés ne sont pas réécrits.

Le pays ne modifie automatiquement ni la devise ni le référentiel comptable du profil. Ces deux choix restent explicites, même si la devise choisie diffère de celle habituellement utilisée dans le pays. Les valeurs historiques sont conservées. Les prix de référence en USD, le calcul des durées et la remise annuelle de **20 %** sont inchangés.

Les montants de TVA et réductions sont calculés sur le HT, comme dans `Facture`. L'arrondi de présentation est effectué après le calcul du net, et non en additionnant des composantes déjà arrondies. Exemple : `3 × 0,10 + 7 × 0,20`, TVA 16 %, remise 5 % donne un net de `1,89`, même si les composantes affichées séparément sont arrondies.

## Inventaire du menu

| Entrée ou groupe | Accès vérifié |
|---|---|
| Clients | Propriétaire/gestionnaire, puis politique du module clients. Le comptable ne possède pas `clients.view`. |
| Services, produits, factures, proformas, dépenses, caisse, paiements, apprenants, comptabilité | Permission du rôle et politique du plan existantes ; la matrice de tests compare les liens aux accès réellement autorisés pour Gratuit, Starter, Pro et Premium. |
| Audit | Propriétaire et désormais comptable, sous réserve de l'abonnement. Pour le comptable, la nouvelle entrée reste masquée si le module n'est pas autorisé par le plan. Gestionnaire exclu ; aucune donnée d'une autre entreprise accessible. |
| RH | Propriétaire/gestionnaire avec droit au module ; masqué au comptable et lorsque le module est verrouillé. |
| Rapports avancés | Propriétaire/comptable avec droit au module ; pas de nouveau droit au gestionnaire. |
| Organisation, utilisateurs, abonnement, suggestions | Restrictions propriétaire existantes conservées. |
| Stock et inventaires | Déjà accessibles par la navigation secondaire de Produits, respectivement selon `stock.view`, `stock.inventory` et le plan. Aucune omission de module principal à corriger. |
| Formations et inscriptions | Déjà présentes dans les actions du module Apprenants, selon les droits correspondants. |
| Défilement | Le menu possède déjà `max-height: 100vh` et `overflow-y: auto` sur ordinateur ; la dernière entrée est atteignable après défilement. Sur mobile le menu est dans le flux de la page. Pas de changement de droits ou de CSS global pour ajouter des entrées déjà présentes plus bas. |

Les badges Premium/abonnement requis existants restent des invitations à changer d'offre ; ils ne confèrent aucun accès métier. Les contrôles serveur ne sont pas modifiés.

## Vérifications et provenance des captures

- Trois tests Node de l'arithmétique de prévisualisation, également exécutés en CI.
- Onze tests Django de régression avec variantes FR/EN : facture multi-lignes enregistrée, TVA nulle conservée à l'édition, pays/devise/référentiel, ancien pays conservé, cycle FC/FCFA/FC et autres devises, taux absents/invalides, ancien taux manuel, matrice rôles/plans et isolation des entreprises pour Audit.
- Contrôle local des catalogues FR/EN ; compilation et extraction des domaines Django/DjangoJS et suite Django complète exécutées par la CI PostgreSQL 14.24, Python 3.14.10, Ubuntu 22.04.
- Docker local indisponible : aucun test de base sur SQLite. Les captures locales utilisent les véritables templates et scripts avec des données fictives ; l'état Premium et les taux sont simulés pour la prévisualisation. Elles ne proviennent ni du VPS ni de comptes de production. Les tests CI exercent les vraies vues et écritures sur une base PostgreSQL de test.
- Edge en FR/EN sur ordinateur et mobile : saisie 105 × 500, prix de catalogue français, plusieurs lignes, trois réductions, ajout/suppression de ligne, conservation des sélections du profil, conversion disponible/indisponible et défilement de la dernière entrée du menu. Six erreurs de devise reproduites avant correction, aucune après.

## Captures avant/après

CI validée : **860 tests Django réussis sur PostgreSQL 14.24**, **3 tests Node réussis**, compilation/extraction des catalogues FR/EN réussies. Le moteur Docker local étant indisponible, les tests de base sont exécutés en CI ; les contrôles navigateur et Node ont également été exécutés sur le poste.

Les captures de facture montrent les montants saisis et la prévisualisation. Le tableau de lignes peut défiler horizontalement sans déplacer la prévisualisation des totaux. Les captures mobiles d'abonnement sont cadrées sur les estimations ; celles du menu sont cadrées sur ses dernières entrées, là où Audit doit apparaître pour le comptable autorisé.

| Parcours | FR ordinateur avant / après | FR mobile avant / après | EN ordinateur avant / après | EN mobile avant / après |
|---|---|---|---|---|
| Facture | [Avant](previews/four-fixes/before/invoice-fr-desktop.png) / [Après](previews/four-fixes/after/invoice-fr-desktop.png) | [Avant](previews/four-fixes/before/invoice-fr-mobile.png) / [Après](previews/four-fixes/after/invoice-fr-mobile.png) | [Avant](previews/four-fixes/before/invoice-en-desktop.png) / [Après](previews/four-fixes/after/invoice-en-desktop.png) | [Avant](previews/four-fixes/before/invoice-en-mobile.png) / [Après](previews/four-fixes/after/invoice-en-mobile.png) |
| Profil | [Avant](previews/four-fixes/before/company-fr-desktop.png) / [Après](previews/four-fixes/after/company-fr-desktop.png) | [Avant](previews/four-fixes/before/company-fr-mobile.png) / [Après](previews/four-fixes/after/company-fr-mobile.png) | [Avant](previews/four-fixes/before/company-en-desktop.png) / [Après](previews/four-fixes/after/company-en-desktop.png) | [Avant](previews/four-fixes/before/company-en-mobile.png) / [Après](previews/four-fixes/after/company-en-mobile.png) |
| Abonnement | [Avant](previews/four-fixes/before/subscription-fr-desktop.png) / [Après](previews/four-fixes/after/subscription-fr-desktop.png) | [Avant](previews/four-fixes/before/subscription-fr-mobile.png) / [Après](previews/four-fixes/after/subscription-fr-mobile.png) | [Avant](previews/four-fixes/before/subscription-en-desktop.png) / [Après](previews/four-fixes/after/subscription-en-desktop.png) | [Avant](previews/four-fixes/before/subscription-en-mobile.png) / [Après](previews/four-fixes/after/subscription-en-mobile.png) |
| Menu comptable | [Avant](previews/four-fixes/before/navigation-fr-desktop.png) / [Après](previews/four-fixes/after/navigation-fr-desktop.png) | [Avant](previews/four-fixes/before/navigation-fr-mobile.png) / [Après](previews/four-fixes/after/navigation-fr-mobile.png) | [Avant](previews/four-fixes/before/navigation-en-desktop.png) / [Après](previews/four-fixes/after/navigation-en-desktop.png) | [Avant](previews/four-fixes/before/navigation-en-mobile.png) / [Après](previews/four-fixes/after/navigation-en-mobile.png) |
