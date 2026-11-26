# Barre latérale — design validé

Branche `codex/sidebar-handoff`, issue de `main` à `d7be76f`.
Le document Figma `docs/sidebar-handoff.md` n'étant pas exporté dans le dépôt, la capture et les couleurs précisées par l'utilisateur servent de référence, conformément à son accord.

## Changement

La barre Django existante reçoit un fond bleu `#B9D8E5`, une carte d'entreprise foncée `#14384D` avec motif circulaire en CSS, un nom secondaire turquoise `#61D0CC` et un badge de rôle doré `#D7BF7A`. Les liens restent foncés `#123D53` ; l'actif conserve un fond bleu pâle `#D8EEF2` et un repère turquoise `#1CAAA6`.

Le survol des liens inactifs devient blanc. Le survol de l'actif conserve son fond, son repère et ses dimensions ; aucun lien ne se déplace ou ne se redimensionne. La largeur de 280 px sur ordinateur, les groupes, libellés, icônes, routes, permissions et règles mobiles existants sont préservés. Seuls les liens défilent ; l'identité et le pied de barre restent fixes. Aucune modification de React, des fonctionnalités métier ou des logos de l'accueil, de la connexion et de l'entreprise dans le tableau de bord.

## Aperçus

Données exclusivement fictives, dont `demo@example.invalid`. Captures Edge locales ; aucun accès au VPS ou à une base réelle.

| Vue | Capture |
| --- | --- |
| Ordinateur FR, lien inactif survolé | [Voir](desktop-fr-hover.png) |
| Ordinateur FR, actif survolé | [Voir](desktop-fr-active-hover.png) |
| Mobile FR, menu ouvert | [Voir](mobile-fr-open.png) |
| Mobile FR, menu replié | [Voir](mobile-fr-collapsed.png) |
| Ordinateur EN | [Voir](desktop-en.png) |
| Mobile EN | [Voir](mobile-en-open.png) |

## Contrôles locaux

- 10 tests Django ciblés : `joatham_dashboard.test_sidebar` et `joatham_dashboard.test_company_logo`, OK sur PostgreSQL 14.24 / Python 3.14.10.
- 9 tests JavaScript, OK.
- 80 scénarios navigateur FR/EN : propriétaire, gestionnaire, comptable, super-admin et Starter ; formats 1440×900, 1440×600, 390×844 et 320×740. Vérification du contraste, de la carte et du motif, des états actif/survolé et de l'absence de variation de position ou de taille. Défilement indépendant, pied fixe, menu mobile, Échap, redimensionnement et accès sans JavaScript vérifiés.
- Catalogues Django et DjangoJS compilés et contrôlés avec `check_translations --extract` ; aucune nouvelle chaîne ni modification de traduction nécessaire.
- `git diff --check` sans erreur.

La CI de la PR exécute également les contrôles Nginx et la suite Django complète sur Ubuntu 22.04 / PostgreSQL 14.24. Aucune fusion ni aucun déploiement autorisé.
