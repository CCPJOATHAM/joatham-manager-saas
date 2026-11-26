# Barre latérale — proposition locale à valider

Branche `codex/sidebar-design`, issue de `origin/main` à `0c74ad3` (PR #45).
Présentation validée le 26 novembre 2026 ; publication de la branche et ouverture d'une PR de revue autorisées. Aucune fusion ni aucun déploiement autorisé.
Le travail Nginx non commité présent dans le checkout initial est conservé séparément et intact.

## Audit

- La barre de `joatham_dashboard/base.html` est commune aux quatre rôles : propriétaire (et alias historique `admin`), gestionnaire, comptable et super-admin. Les modules métier et la base comptable active l'étendent.
- `navigation.py` filtre déjà les entrées par rôle, permissions, abonnement et module. Les liens verrouillés, badges de forfait et compteurs de messages font partie de ces résultats.
- Les icônes de l'ancien template comparaient les libellés à des chaînes françaises : certaines traductions anglaises recevaient donc une icône de remplacement sans rapport avec le module.
- Le défilement de l'ancienne barre concernait l'ensemble de la colonne, pied compris. Le conteneur partagé empêchait aussi son positionnement sticky de rester attaché à l'écran pendant le défilement de la page principale. Sur téléphone, la liste de liens s'étalait avant le contenu principal.
- Les anciens fichiers `templates/compta_base.html` et `joatham_pro/templates/compa_base.html` n'ont pas de références trouvées dans les templates actifs. Ils sont conservés. La navigation horizontale propre au module Produits est également conservée.

## Proposition

- Aucun logo ni filigrane dans la barre latérale : l'image et ses styles ont été supprimés, sans remplacement par une image d'arrière-plan. Le nom de la plateforme reste en texte simple dans l'en-tête ; la disposition et les groupes acceptés sont conservés.
- Fond bleu-vert clair renforcé, inspiré de JOATHAM (`#dceff0`, `#d2e9e9`, `#e0ecf3`), avec libellés et icônes foncés et repère actif turquoise conservé. Le dernier ajustement ne modifie que les trois couleurs du dégradé, sans changement de disposition ou de comportement.
- Le logo officiel reste sur l'accueil public et la connexion. Les templates concernés, le fichier du logo officiel, l'en-tête d'identité de l'entreprise et son CSS/JavaScript ne présentent aucun diff par rapport à `HEAD`.
- Groupes : Espace de travail, Ventes et services, Activités et équipes, Finances et suivi, Organisation ; Administration SaaS pour la plateforme. Les groupes vides sont absents et une entrée future non classée reste visible dans Autres.
- Icônes déterminées par une clé de route stable, indépendamment de la langue. État actif turquoise avec repère latéral et `aria-current="page"` ; contour de focus au clavier.
- Navigation dans une zone défilante dédiée. Logo, identité et pied restent en place pendant son défilement, y compris sur écran de faible hauteur. Sur ordinateur, la barre est fixée à l'écran et sa colonne de 280 px reste réservée au sein de la grille.
- À 1120 px et moins : bouton de menu accessible, menu initialement replié, activation tactile ou clavier, Échap ferme le menu et rend le focus au bouton. Sans JavaScript, tous les liens restent affichés et accessibles.
- Les routes, contrôles d'accès, fonctionnalités des modules, prix et données persistées ne changent pas. Le seul ajout au générateur de navigation est une clé de présentation ; son filtrage et ses règles d'état sont inchangés.

## Contrôle des liens

Comparaison indépendante avec le générateur original récupéré à `HEAD` : URL, libellé, état actif, verrouillage et badges identiques avant regroupement, dans les deux langues.

| Scénario synthétique | Entrées FR | Entrées EN |
| --- | ---: | ---: |
| Propriétaire Premium | 19 | 19 |
| Gestionnaire Premium | 13 | 13 |
| Comptable Premium | 13 | 13 |
| Super-admin sans entreprise | 8 | 8 |
| Propriétaire Starter | 11 | 11 |

Les tests de regroupement couvrent les quatre rôles sur Starter, Pro et Premium, ainsi qu'un lien futur, les badges, les états désactivés, le nom d'entreprise d'origine et l'absence de données d'une autre entreprise. Le test existant `test_navigation_matches_primary_modules_permissions_and_plans_in_both_languages` couvre aussi le forfait Gratuit et les permissions effectives des modules.

## Vérifications locales

- Python 3.14.10, Django 6.0.10, PostgreSQL **14.24**, cluster temporaire dédié sur `127.0.0.1`, supprimé après les contrôles. Aucun accès à une base réelle.
- Tests ciblés `joatham_dashboard.test_sidebar joatham_dashboard.test_company_logo joatham_dashboard.tests.PublicHomeTests` après retrait du logo : **33 tests, OK**, en 8,495 s. Vérification FR/EN de l'absence d'image et de filigrane dans le composant, conservation du logo propre à chaque entreprise et contrôles de l'accueil public.
- `node --test tests/js/*.test.cjs` : **9 tests, OK**, dont trois nouveaux tests du menu mobile/clavier/redimensionnement.
- `compilemessages -l fr -l en` et `check_translations --extract` : **OK** pour les domaines Django et DjangoJS. Les nouveaux textes sont dans `django.po` et les `.mo` compilés ; le domaine DjangoJS ne contient aucune nouvelle chaîne et reste inchangé après extraction/compilation.
- Navigateur Edge local : **80 scénarios, OK** (avant/après, cinq scénarios rôle/forfait, FR/EN, 1440×900, 1440×600, 390×844 et 320×740). Pas de débordement horizontal ; une entrée active ; mêmes icônes et liens dans les deux langues ; dernier lien atteignable ; pied immobile ; Échap, retour au desktop et accès sans JavaScript vérifiés. Aucune erreur JavaScript.
- Suite Django complète sur PostgreSQL **14.24**, avant les derniers ajustements purement visuels : **954 tests, OK**, en 456,583 s. Elle n'a pas été relancée pour ce retrait d'image ; les 33 tests ciblés, les 9 tests JavaScript et le contrôle d'extraction/compilation FR/EN ont été relancés et passent.
- `git diff --check` : aucun défaut constaté.

Ces contrôles ont été effectués localement sous Windows. La publication de la PR déclenche la CI GitHub du projet (Ubuntu 22.04, Python 3.14.10 et PostgreSQL 14.24) ; son résultat doit être vérifié sur le SHA publié. Les aperçus ne constituent pas une vérification sur un téléphone physique.

## Aperçus

[Galerie avant/après FR/EN](previews/sidebar/README.md). Les pages utilisent les vrais templates et les vrais résultats du filtre de navigation avec des données fictives. `demo@example.invalid`, les noms et les montants montrés sont exclusivement des données de prévisualisation. Pour le super-admin, le template de plateforme est utilisé ; aucune identité d'entreprise n'est transmise.

Les scripts de génération et les rapports JSON locaux sont conservés dans le dossier d'artefacts voisin du worktree : `render-sidebar.py`, `preview-sidebar.mjs`, `run-sidebar-pg14.py`, `sidebar-preview/navigation-parity.json` et `sidebar-preview/browser-checks.json`.

## Fichiers concernés

- `core/context_processors.py` : transmet les groupes, en conservant la liste autorisée existante.
- `joatham_dashboard/services/navigation.py` : clé stable de présentation uniquement.
- `joatham_dashboard/services/sidebar_presentation.py` : regroupement sans filtrage.
- `joatham_dashboard/templates/joatham_dashboard/base.html` et `includes/sidebar*.html` : extraction du composant, liens et icônes.
- `static/joatham_dashboard/css/sidebar.css`, `static/joatham_dashboard/js/sidebar.js` : présentation et repli du menu.
- `locale/{fr,en}/LC_MESSAGES/django.{po,mo}` : nouveaux intitulés ; retrait de deux anciens sous-titres désormais inutilisés.
- `joatham_dashboard/test_sidebar.py`, `tests/js/sidebar.test.cjs` : régressions.
- Ce rapport et `docs/previews/sidebar/` : preuves de revue.

Le regroupement et la version finale sans logo ni filigrane, avec sa teinte bleu-vert renforcée, ont été validés pour ouverture d'une PR. Les aperçus de la première proposition sont conservés sous `docs/previews/sidebar/v1/`. Aucun module n'est supprimé et aucune décision de droit d'accès n'est prise par la couche de présentation.
