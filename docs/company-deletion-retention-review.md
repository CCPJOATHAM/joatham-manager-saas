# Demande de suppression d'entreprise : audit, gel et validation

Branche créée depuis `origin/main` à `8870b3e`. Aucun accès au VPS, aucune entreprise réelle programmée ou supprimée, aucune migration appliquée à une base utilisateur ou de production. Processus : LOCAL → TEST → COMMIT → VALIDATION → MERGE → PROD ; PR en brouillon.

## Périmètre confirmé le 22 novembre 2026

**JOATHAM Manager est accessible à l'international ; la RDC est le seul pays d'exploitation effective confirmé à ce jour, et le lancement commercial commence en Afrique.** Les pays proposés à l'inscription ne constituent pas une liste de marchés exploités ou de politiques juridiques validées.

L'utilisateur a expressément demandé de **bloquer toute purge automatique ou irréversible tant que les règles de conservation ne sont pas validées**. Cette version ne contient donc aucun chemin d'exécution effaçant une entreprise, ses comptes, ses documents ou ses données métier. La fonction de purge refuse toujours ; un drapeau d'environnement ou une référence d'approbation fournie à la commande ne la débloque pas. Une évolution distincte, revue et autorisée, sera nécessaire.

Les 30 jours représentent une période de récupération du produit. Ils ne déclenchent ni effacement ni validation juridique. Le gel est transitoire : il ne valide pas une conservation indéfinie. Après cette période, la demande reste en gel de conservation et l'annulation demeure possible puisque rien n'a été purgé.

## Constats de l'audit

- `Entreprise` porte l'identité, les coordonnées, le référentiel comptable et un drapeau `is_active`. Les comptes utilisateurs et abonnements d'entreprise dépendent d'elle. Les forfaits `Abonnement` sont des objets globaux et ne doivent pas être assimilés aux données d'un client.
- L'inventaire statique initial a relevé **130 relations** dans les modèles du projet, sans lire de base. De nombreuses relations utilisent `CASCADE` : facturation, paiements, caisse, comptabilité, apprenants, RH, messages, stock et audit. Les enfants indirects comprennent notamment lignes de facture, lignes d'écriture, participants et pièces jointes. Une suppression naïve de la racine n'est pas une procédure de conservation.
- La désactivation existante met l'entreprise et ses utilisateurs à l'arrêt et suspend l'abonnement ; la suspension d'abonnement et la réactivation individuelle existent également. Ces fonctions sont conservées. La nouvelle demande est distincte et ne réécrit ni les drapeaux individuels ni l'état commercial de l'abonnement.
- Les espaces d'entreprise utilisent les contrôles de tenancy ; les API configurées utilisent l'authentification de session. Le nouveau verrou d'accès vérifie aussi la demande persistée, indépendamment de `is_active`, y compris pour un utilisateur staff dans Django admin. Les helpers de tenancy et la connexion appliquent le même verrou.
- Les notifications financières anonymes/prestataires ne sont pas interrompues par ce contrôle utilisateur. Les données supplémentaires qu'elles peuvent produire sont conservées. Programmer une suppression n'est ni un remboursement ni une annulation d'engagement externe.
- L'audit avait une dépendance `CASCADE` à l'entreprise. La migration `core.0019_company_deletion_workflow` la remplace par `PROTECT` et crée la demande persistante, elle aussi protégée. La suppression directe d'entreprise est retirée de Django admin ; les traces d'audit y sont consultables mais non ajoutables, modifiables ou supprimables.

## Parcours livré

1. Le super-administrateur ouvre l'action distincte **Programmer la suppression** depuis la liste des entreprises. Le récapitulatif affiche le nom, l'identifiant, les principales catégories de données, les limites de l'export et le gel de la purge.
2. Export et programmation passent par POST avec CSRF, nom exact et motif obligatoire (1 à 2 000 caractères). La permission est vérifiée dans la vue **et** dans les services, avec relecture du compte actif. Un compte privilégié de plateforme rattaché à la cible bloque la programmation.
3. La programmation verrouille l'entreprise, vérifie l'inventaire, mémorise l'état d'accès et la date de récupération, puis bloque l'accès et révoque les sessions indexées. Les anciens accès non indexés restent bloqués par le middleware. Une action concurrente ou répétée ne repousse pas la date. Motif, auteur, date et catégories sont enregistrés dans la même transaction ; une panne d'audit annule la programmation.
4. L'annulation, elle aussi confirmée par nom et motif, restaure uniquement le drapeau d'accès antérieur. Une entreprise auparavant inactive reste inactive ; un compte auparavant désactivé reste désactivé ; les dates d'abonnement ne sont pas prolongées. Les sessions déjà révoquées ne sont pas recréées.
5. La simulation administrative est strictement en lecture seule. Elle fournit des comptes par modèle, des obstacles de conservation, les fichiers référencés, les éventuelles relations inter-entreprises et une empreinte du périmètre. `purge_permitted` reste toujours `false` et `policy_blocker` vaut `retention_rules_not_approved`.
6. Une tentative de purge réelle authentifiée et confirmée est refusée et auditée. Aucun cron, timer ou bouton de purge irréversible n'est ajouté.

Configuration :

- `JOATHAM_COMPANY_DELETION_GRACE_DAYS=30` : entier positif, copié dans la date de chaque nouvelle demande. Un changement ultérieur ne raccourcit pas les demandes existantes.
- `JOATHAM_COMPANY_EXPORT_MAX_ROWS=50000` : plafond de l'inventaire structuré. Au-delà, l'opération échoue sans modification ; un export/précontrôle administratif dédié est nécessaire. Aucun paramètre n'autorise l'effacement.

Commande de simulation à utiliser seulement par un opérateur autorisé sur un environnement validé (aucune exécution sur le VPS dans ce chantier) :

```text
python manage.py purger_entreprise IDENTIFIANT --actor-id IDENTIFIANT_SUPER_ADMIN --simulate
```

Omettre `--simulate` produit également une simulation. `--execute`, même accompagné du nom, du motif, de l'empreinte et d'une référence de conservation, est refusé : il n'existe pas encore de politique de purge approuvée.

## Export, confidentialité et limites

L'export est une pièce jointe JSON privée (`no-store`, `nosniff`), limitée à l'entreprise visée et auditée avant sa remise. Le parcours ne déduit aucune appartenance par similitude d'email ou de nom. Les relations inverses sont parcourues ; les références sortantes ne chargent ni les autres entreprises ni les catalogues globaux. Les identifiants externes de forfait et d'acteur global ne servent pas à exporter leurs objets.

Les mots de passe, jetons, clés, identifiants de session, sessions, URL de checkout, jetons de notification, identifiants de checkout et payloads bruts de prestataires sont exclus ; les clés techniques sensibles connues sont aussi filtrées dans les objets JSON. Les champs libres ne sont ni corrigés ni traduits : les opérateurs doivent aussi contrôler les secrets qu'un utilisateur aurait lui-même copiés dans une note libre.

Une relation incohérente vers une autre entreprise bloque l'export plutôt que de livrer des données étrangères. L'export ne contient pas les fichiers binaires, les sessions, les tables globales d'administration, les invitations sans lien structurel d'entreprise, les sauvegardes ou les copies détenues par un prestataire. Il ne remplace pas `pg_dump` ni un archivage légal. Il est destiné à la revue ; aucun import/restauration de ce JSON n'est fourni. Les fichiers restent dans leur stockage actuel : leur chemin référencé ne constitue pas une suppression ou un chiffrement.

**Point bloquant de confidentialité avant mise en ligne :** l'opérateur a confirmé des alias publics `/media/` dans les deux sites Nginx. Ils contournent le verrou Django. Le [correctif distinct des médias privés](private-media-remediation.md) remplace les liens privés, protège les téléchargements et fournit un fragment Nginx refusant les anciens chemins privés, tout en préservant les logos publics. Il doit être revu et sa configuration appliquée aux deux sites après accord ; le commit applicatif seul ne corrige pas le serveur. Voir aussi [l'audit initial](private-media-access-audit.md) et ses commandes en lecture seule. Aucun fichier utilisateur ni serveur n'a été consulté par l'agent. La mise à l'écart reste un archivage logique dans la base existante, pas un coffre d'archives légal indépendant.

Les requêtes déjà en cours au moment de la programmation peuvent se terminer ; les requêtes suivantes sont bloquées. Les échanges nécessaires à la traçabilité financière sont conservés. La confidentialité des sauvegardes et la réapplication d'un gel après restauration d'une sauvegarde doivent faire partie du protocole d'exploitation.

## Règles de conservation à faire valider

Aucune durée juridique ni autorisation d'effacement n'est déduite du pays ou du délai de 30 jours.

| Catégorie | Comportement actuel | Décision nécessaire avant toute purge |
| --- | --- | --- |
| Factures, paiements, justificatifs, caisse et comptabilité | Conservation intégrale ; purge bloquée | Textes comptables/fiscaux applicables à l'entreprise en RDC, durée et point de départ, intégrité/restitution, contrôles et contentieux |
| RH, rémunérations, documents et apprenants | Conservation ; purge bloquée | Obligations sociales/sectorielles, données personnelles, restrictions et personnes habilitées |
| Audit, demandes, motifs et identité de l'opérateur | Conservation protégée ; aucune cascade | Finalité probatoire, durée, minimisation des données et journal d'accès |
| Coordonnées, comptes, messages et données commerciales | Archivage logique et accès bloqué | Base de conservation, demandes des personnes, anonymisation éventuelle et validation des dépendances |
| Fichiers, exports, sauvegardes, prestataires | Non effacés par cette version | Copies, chiffrement, accès, cycle de sauvegarde, suppression différée des copies et preuve de traitement |
| Marchés internationaux futurs | Aucune règle présumée | Pays effectivement desservis, lois applicables, transferts et politique locale avant extension |

Sources institutionnelles à examiner avec le conseil compétent, sans en déduire ici une politique validée : [publication officielle de l'AUDCIF par l'OHADA](https://www.ohada.org/publication-du-nouvel-acte-uniforme-relatif-au-droit-comptable-et-a-l-information-financiere-audcif/) et [Code du numérique mis à disposition par le ministère congolais de l'Économie numérique](https://economienumerique.gouv.cd/mediatheque/documents). Ces liens ne constituent pas une validation juridique du produit. L'accessibilité mondiale du site ne prouve pas qu'une même règle s'applique partout.

## Vérification et revue

Tests ciblés : permissions, CSRF, nom exact, motif, accès aux API, sessions, état antérieur, délai mémorisé, annulation après 30 jours sous gel, export et filtrage des secrets, relations inter-entreprises, rollback sur panne d'audit, concurrence PostgreSQL, simulation sans écriture et impossibilité d'exécuter la purge. Les événements et l'interface sont vérifiés en FR/EN ; les textes libres restent inchangés.

La migration est générée hors connexion puis appliquée uniquement aux bases de test PostgreSQL, locales et de CI. Les 21 tests ciblés ont réussi localement sur PostgreSQL 14.24 (conteneur jetable, port lié à 127.0.0.1, base test_joatham_deletion_tests). La suite complète et la CI sont également exécutées avant validation. Aucune exécution réelle de programmation ou de purge sur une base utilisateur. Les résultats de la CI et les rendus sont ajoutés à la description de la PR avant validation. Ni forfaits, ni prix, ni moyens de paiement ne changent.

[Rendus FR/EN, ordinateur et mobile](previews/company-deletion/README.md) : 16 captures et 30 contrôles de présentation, avec données fictives et accès aux bases interdit pendant le rendu.
