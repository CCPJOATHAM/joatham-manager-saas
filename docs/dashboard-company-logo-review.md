# Logo de l'entreprise dans le tableau de bord

Préparation locale du 25 novembre 2026. Branche `codex/dashboard-company-logo`, créée depuis le main distant actualisé à `d5de30b`. Worktree distinct pour conserver les chantiers existants. Aucun commit, push, appel à la production, fusion ou déploiement.

## Source réutilisée

Le champ existant est `joatham_users.models.Entreprise.logo` (`ImageField`, `upload_to="entreprises/logos/"`). Organisation utilise ce champ via son formulaire et affiche `entreprise.logo.url`. Les factures/documents passent par `build_entreprise_identity` et `build_logo_data_uri` dans `core/services/company_profile.py`, notamment depuis `joatham_billing/views.py`.

Le contexte commun `core.context_processors.entreprise_identity` prépare déjà `entreprise_identity.logo_url` à partir de l'entreprise de l'utilisateur connecté. Le composant ajouté lit **exactement cette valeur**, sans nouvelle requête, nouveau champ, nouveau stockage ou nouvelle source de remplacement. Aucun formulaire de téléversement n'est changé.

## Modification proposée

Les trois tableaux de bord (propriétaire, gestionnaire, comptable) affichent le logo à côté du nom dans l'en-tête d'identité, grâce à un composant partagé. Le nom reste du texte, dans la langue et l'orthographe saisies. Le titre de l'entreprise occupe l'en-tête, les intitulés métier restent dans les bannières existantes et les sous-titres de rôle sont conservés.

- Logo dans une surface blanche, proportions conservées par `object-fit: scale-down`, sans recadrage ni agrandissement au-delà de la taille native d'une petite image.
- Dimensions adaptées au mobile et noms longs pouvant revenir à la ligne.
- Initiale de la même entreprise en l'absence de logo, ou lorsque le navigateur ne peut pas charger le fichier.
- Image décorative à côté du nom accessible, sans annonce redondante. Le script gère aussi un échec survenu avant son chargement.
- CSS et JavaScript chargés uniquement par les trois tableaux de bord ; aucun changement du template de base partagé.
- Pas de filigrane supplémentaire : la bannière et ses contrastes restent inchangés.

Les vues, permissions, routes médias, configurations Nginx, services métier, modèles et migrations sont inchangés. L'isolation vérifiée concerne **le logo affiché dans chaque tableau de bord** : les permissions existantes des URL de logos sont conservées, sans promettre une nouvelle confidentialité de ces fichiers publics.

## Contrôles locaux

**34 tests Django réussis à nouveau en 19,875 s sur PostgreSQL 14.24**, base temporaire distincte, médias fictifs temporaires et HTTP extérieur bloqué. Commande logique : `manage.py test joatham_dashboard.test_company_logo joatham_dashboard.tests.DashboardAccessTests core.tests_company`, avec le runner PostgreSQL isolé local.

Les six nouveaux tests vérifient les trois rôles, FR/EN, deux entreprises aux logos distincts, l'ignorance d'un identifiant d'entreprise étrangère dans la query string, les remplacements, les noms échappés sans réécriture, l'accès anonyme et l'utilisation du même champ que les documents. Les tests existants de tableau de bord et d'Organisation passent.

**180 contrôles Edge headless réussis** : avant/après, trois rôles, FR/EN, cinq états (logo, absence, fichier introuvable, nom long, image fictive 16×16 px), trois largeurs (1440, 390, 320 px). Pas de débordement horizontal, logo chargé avec `scale-down`, repli visible après erreur, aucun mélange de source ni exception JavaScript. Les actions/méthodes/CSRF des formulaires, les liens, les boutons et les options de langue sont comparés à l'existant. Aucun formulaire n'est soumis.

## Ajustements après la première revue

Le cadre passe de 96×72 à 128×104 px sur ordinateur, et de 68×56 à 96×88 px sur mobile. Les marges internes de l'image diminuent à 3 px / 2 px. Les éventuelles marges déjà présentes dans le fichier ne sont pas supprimées : aucune image n'est découpée ou réenregistrée. Une image de faible définition conserve sa taille native au lieu d'être artificiellement grossie.

Sur mobile uniquement, dans la feuille CSS réservée aux tableaux de bord : langue et bouton restent sur une ligne ; profil, actions de rôle et déconnexion se répartissent sur des lignes compactes ; email et rôle restent visibles sous forme de texte plus léger. Les éléments interactifs font au moins 44 px de haut. Les formulaires et leurs champs n'ont pas changé ; l'ordre de tabulation des commandes reste celui du DOM.

Douze comparaisons supplémentaires entre la première proposition et la révision (FR/EN, avec/sans logo, 1440/390/320 px) vérifient la réduction de la zone de commandes et l'agrandissement des images de qualité suffisante. Exemple FR à 390 px : hauteur de l'image affichée **42 → 82 px**, zone de commandes **275 → environ 125 px**, en-tête complet **477 → environ 304 px**. À 320 px, l'en-tête passe d'environ 497 à 314 px.

`demo@example.invalid` est **uniquement une donnée fictive du script local de prévisualisation**, attribuée à un objet utilisateur non enregistré. Cette valeur n'existe ni dans les templates, ni dans les scripts/CSS du produit, ni comme valeur par défaut d'un modèle. En utilisation réelle, l'en-tête conserve `request.user.email` ou son nom d'utilisateur, comme auparavant. Aucun compte ou email réel n'a été modifié pour les aperçus.

Les catalogues FR/EN sont compilés ; `check_translations --extract`, `git diff --exit-code -- locale` et `git diff --check` réussissent. Aucun texte d'interface nouveau n'est introduit : les textes et traductions existants sont réutilisés, le JavaScript n'affiche aucun message.

La suite complète et la CI distante ne sont pas déclenchées pour cette modification locale de présentation. Les sources de facturation/PDF, permissions, paiement et tarification sont identiques à main.

## Aperçus et diff

[Galerie avant/après FR/EN et rendus de remplacement](previews/dashboard-company-logo/README.md) : captures avec/sans logo, vues 320 px et première proposition conservée pour comparaison ; données fictives et rendus des templates complets sans accès à une base. Le logo de démonstration est un fichier déjà présent dans le projet (`static/images/logo.png`), servi comme le fichier d'un champ `Entreprise.logo` fictif ; il ne devient pas un logo par défaut dans le produit.

Sur mobile, les captures cadrent le contenu du tableau de bord après défilement du menu existant ; ce menu n'est pas refondu. Les captures ne proviennent pas d'un compte réel.

Le diff textuel de revue exclut seulement les PNG, disponibles dans la galerie ; un diff complet binaire est également exporté localement. La branche et tous les fichiers restent non publiés pour validation.
