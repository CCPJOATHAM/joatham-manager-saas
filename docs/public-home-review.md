# Accueil public : revue de présentation

Branche `codex/public-home-polish`, créée depuis le dernier `origin/main` (`53b1c43`). L'état Git initial était propre. Aucun accès au VPS, fusion ou déploiement.

## Examen et changements

- Page : `joatham_dashboard/templates/joatham_dashboard/public_home.html`, avec son CSS et son JavaScript dédiés. Le même template sert aussi `/decouvrir/` ; ces deux routes sont vérifiées.
- Logo officiel existant : `static/joatham_dashboard/img/login-logo.webp` (600 × 234, transparent, utilisé sur la connexion). Réutilisé dans l'en-tête et le pied de page ; aucune image ni symbole de marque créé.
- Le sélecteur de langue était limité à 92 px. Il affiche désormais un libellé explicite et le nom complet de la langue. La sélection déclenche le même POST protégé ; sans JavaScript, un bouton « Appliquer la langue » reste disponible. Le sélecteur partagé des autres pages n'est pas modifié. Le retour conserve aussi la section courante.
- La hauteur de l'en-tête pouvait varier alors que son décalage de défilement restait constant. La hauteur réelle est maintenant mesurée pour les ancres et le lien d'évitement. Le retour en haut cible le document, plutôt que l'en-tête déjà collé à l'écran. Sur téléphone, l'en-tête reste dans le flux ; sans JavaScript, il ne devient pas fixe.
- Le menu compact affiche des liens sur plusieurs lignes, sans défilement horizontal caché. Le bouton signale son état, se ferme après navigation et via Échap, avec retour du focus.
- Les commandes du carrousel restent toutes visibles sur téléphone, avec cibles tactiles de 44 px, flèches et raccourcis existants. Le cadre des captures est stable et conserve l'image entière. Les boutons exposent leur état avec `aria-pressed`. La pause au survol/focus ne reprend plus pendant une interaction au clavier ; les intervalles existants sont conservés.
- Espacements, largeur de contenu et hiérarchie des titres harmonisés. Les cartes tarifaires alignent leurs prix, détails et boutons sur ordinateur ; sur téléphone elles restent empilées. La remise annuelle reste lisible sur la carte bleue.

## Périmètre préservé

Aucune modification des vues commerciales, du calcul des prix, des forfaits ou de la remise annuelle de 20 %. Les valeurs et liens d'inscription mensuels/annuels sont comparés avant/après dans le navigateur. Liens de connexion, inscription, contact, question et ancres conservés. Les contenus FR/EN existants restent en place ; seuls les libellés des nouvelles commandes de présentation sont ajoutés aux catalogues.

Toutes les captures produit et illustrations existantes sont conservées, octet pour octet. `docs/landing_assets.md` documente l'autorisation des illustrations fournies et précise qu'elles ne sont pas des témoignages ou des portraits identifiés de membres de JOATHAM. Aucun remplacement par une prétendue photo réelle n'est effectué.

## Contrôles

- `manage.py check` : réussi ; 6 tests Node existants réussis.
- Extraction/compilation GNU gettext 0.21 FR/EN, domaines django/djangojs ; `check_translations --extract` réussi.
- Deux nouveaux tests Django couvrent les deux routes en FR/EN, les logos, les ancres, le formulaire POST avec CSRF et sa solution sans JavaScript, la persistance de langue et les liens tarifaires.
- Navigateur Edge : 18 parcours FR/EN sur 1440, 1280, 1200, 1024, 768, 760, 390, 320 et 844 px (dont paysage). Contrôles de débordement, nom de langue non tronqué, liens profonds, retour en haut, lien d'évitement, menu au clavier, sept écrans du carrousel, cycles tarifaires et formulaire de langue. Solution sans JavaScript également vérifiée.
- [Captures avant/après](previews/public-home/README.md) : FR/EN, ordinateur 1440 px et téléphone 390 px ; quatre vues par combinaison (début de page, fonctionnalités, tarifs, pied de page). Données de présentation issues des forfaits officiels de repli, sans accès à une base de production et sans soumettre d'inscription ou de paiement.
- Docker local ne démarre pas : aucun test SQLite de remplacement. La suite Django complète est exécutée sur PostgreSQL 14.24 isolé dans la CI du projet ; son résultat final sera consigné dans la PR.

## Avis demandé

Valider la lisibilité du logo et la disposition du menu compact. Aucun nouvel arbitrage commercial. Un futur remplacement des illustrations demanderait une photo JOATHAM identifiée et autorisée ; les visuels actuels sont conservés dans cette PR.
