# CinetPay : initialisation sans URL de paiement

Diagnostic préparé le 24 novembre 2026, validation complémentaire le 25 novembre 2026 dans le worktree isolé `codex/cinetpay-init-diagnostics`, depuis main `4d584a8`. Les travaux Nginx non commités du répertoire principal sont conservés. Aucun accès au VPS, aucun appel API CinetPay (Sandbox compris), aucun paiement réel et aucun déploiement.

## Ce que l'on sait de l'incident

L'opérateur confirme un compte CinetPay Sandbox rattaché à la RDC et une absence de paiement dans la période affichée du tableau prestataire. Il ne dispose pas du statut HTTP ni d'une réponse technique expurgée. **La cause exacte de cet incident n'est donc pas confirmée.** Une absence d'historique sur une période ne prouve ni l'absence d'appel, ni le succès de l'authentification, ni la validité de la requête.

Le message « CinetPay n'a pas retourné d'URL de paiement » provient de `CinetPayPaymentProvider.create_payment` : après authentification, un POST d'initialisation et lecture JSON, aucun `payment_url` / `paymentUrl` n'a été trouvé aux emplacements pris en charge (racine, `data`, `data.details`). Le code initial ne distinguait pas un refus métier en HTTP 200 d'une réponse réussie incomplète. Une authentification réellement rejetée ou un HTTP >= 400 suivait normalement un autre message.

## Défauts prouvés dans le code

1. **Référence trop longue :** `SUB-` + 32 caractères UUID produit 36 caractères, systématiquement pour les nouvelles demandes. Le [validateur officiel CinetPay](https://github.com/cinetpay/cinetpay-python/blob/main/src/cinetpay/validation.py) limite `merchant_transaction_id` à 30. C'est une anomalie de conformité reproductible et une cause plausible de rejet, mais aucune réponse reçue pendant l'incident ne permet encore de l'affirmer comme sa cause unique.
2. **Refus métier masqué :** `_post_json` vérifiait seulement le statut HTTP. Une réponse JSON d'erreur en HTTP 200 arrivait à la recherche d'URL puis au message générique. Le [client HTTP officiel](https://github.com/cinetpay/cinetpay-python/blob/main/src/cinetpay/http/http_client.py) examine également les codes métier. Le correctif fait ce contrôle à l'initialisation, sans changer la sémantique des statuts de transaction/webhooks.
3. **Diagnostic Sandbox incorrect :** la recherche des mots « sandbox/test/preprod » dans l'URL ne reconnaissait pas `api.cinetpay.net`. Ce domaine pouvait donc être classé comme production. Le [SDK officiel](https://github.com/cinetpay/cinetpay-python) distingue `api.cinetpay.net` (Sandbox) et `api.cinetpay.co` (production).
4. **Journaux trop larges :** le message d'URL absente journalisait un payload masqué par noms de clés connus. Les descriptions libres, URL contenant des jetons et variantes de clés pouvaient subsister. Le correctif remplace ce journal par une liste fermée de métadonnées, sans payload, coordonnées client, URL, description libre, clé ou jeton.

## Correctif proposé

- Nouvelles références limitées à 30 caractères (`SUB-` + 26 caractères hexadécimaux UUID), avec le contrôle de collision existant. Aucun identifiant historique n'est tronqué ou réécrit.
- Refus des codes métier d'erreur ou statuts explicites d'échec à l'initialisation ; message traduit existant « CinetPay a refusé la requête ». Les codes numériques reconnus suivent le client officiel ; les enveloppes historiques sans code restent compatibles si elles fournissent une session complète.
- Contrôle de la forme JSON ; distinction erreur HTTP, JSON invalide, refus métier, URL absente/invalide et jeton de notification absent. Une URL retournée doit être HTTPS, avoir un hôte et ne pas embarquer d'identifiants. Aucune URL de paiement n'est fabriquée à partir d'un jeton.
- Journalisation de chaque réponse POST avec statut HTTP, code métier numérique borné, statut issu d'une liste fermée et **noms de champs connus seulement**. Les champs inconnus et leurs noms sont exclus. Aucun corps brut ou message du prestataire n'est émis ; les exceptions réseau ne propagent plus leur texte dans une chaîne d'erreur affichable.
- Classification correcte du domaine Sandbox dans le diagnostic existant. Le drapeau `JOATHAM_PAYMENT_SANDBOX` ne choisit toujours pas automatiquement les clés ou les endpoints : aucune bascule de compte ni de production n'est faite par ce correctif.
- Conservation de la vérification du jeton de notification, de la vérification canonique du prestataire, de l'idempotence et de l'activation seulement après confirmation fiable. L'échec d'initialisation annule la création de la demande dans la transaction existante.
- Prix USD, conversion CDF et réduction annuelle de 20 % inchangés. Aucun minimum prestataire n'est contourné en augmentant un prix.

## Configuration RDC / Sandbox à contrôler sans secrets

Le fichier d'exemple de production prévoit déjà le mode Sandbox, le canal `PUSH`, la devise `CDF` et les trois endpoints v1 sur `api.cinetpay.net`. Le fonctionnement automatique y reste désactivé par défaut. Ce fichier d'exemple ne démontre pas la configuration effective du VPS.

L'opérateur doit vérifier localement, sans partager les valeurs sensibles :

- Cohérence des domaines d'authentification, initialisation et vérification avec le compte Sandbox. Ne pas mélanger v1 et Checkout v2. `site_id` et le secret HMAC historique ne remplacent pas les identifiants API v1.
- Présence des identifiants v1 du compte RDC ; aucune clé ou aucun mot de passe ne doit être copié dans un compte rendu. Le SDK choisit les identifiants par pays ; ajouter arbitrairement un champ `country` à notre payload n'est pas un correctif documenté.
- Devise réellement activée pour ce compte et les opérateurs proposés. Le code sait initialiser CDF ou USD selon la configuration ; cela ne prouve pas leur habilitation commerciale effective. Les montants minimum/maximum, limites et moyens actifs doivent être confirmés par le prestataire, sans modifier nos tarifs.
- Canal v1 `PUSH` et `direct_pay=False` pour obtenir une page de paiement. Le réglage historique `CHANNELS=MOBILE_MONEY` ne remplace pas le champ v1 `channel`.
- URLs de retour et notification absolues, accessibles au prestataire, limites de longueur des champs et formats du contact. Les limites documentées peuvent expliquer d'autres refus ; aucune réponse brute n'est disponible pour identifier lequel.

Aucune commande de ce chantier ne lit les fichiers d'environnement réels ni ne consulte le tableau CinetPay. Le compte Sandbox/RDC est un fait communiqué par l'opérateur, pas une connexion effectuée par l'agent.

## Récupérer une trace minimale, si nécessaire

La trace n'est pas indispensable pour corriger les défauts prouvés ci-dessus. Elle reste nécessaire pour attribuer précisément l'incident observé. **Ne pas reproduire un paiement uniquement pour fabriquer cette trace.**

Les journaux du service `joatham` sont l'endroit à examiner localement par l'opérateur. Ne pas afficher ou transmettre leur sortie brute : l'ancienne version peut y avoir écrit des URL ou descriptions sensibles malgré son masquage partiel.

Le filtre relisible `scripts/inspect_cinetpay_log.py` fonctionne sans Django, sans réseau et sans écriture. Il ne produit que `http_status` et les noms de champs connus aux emplacements reconnus. Les valeurs, codes métier, descriptions, jetons et URL ne sortent pas du filtre. En cas d'échec de parsing, il ne réaffiche jamais la ligne d'entrée.

Exemple **uniquement si le filtre a été relu et est déjà disponible sur la machine qui examine le journal**, pas une commande d'installation ou de déploiement :

```bash
journalctl -u joatham --since '2026-11-24 00:00:00' --no-pager -o cat | python3 /CHEMIN_APPROUVE/inspect_cinetpay_log.py
```

Ne pas exécuter cette commande avec le chemin fictif inchangé. Adapter la période à l'incident et au fuseau de la console. Aucune copie vers le VPS n'est effectuée ici. Le script peut aussi filtrer un journal déjà conservé dans un environnement d'inspection autorisé ; ne pas transmettre un export brut au chat.

Avec l'ancien journal « no checkout URL », **le statut HTTP exact n'était pas enregistré** : le filtre retourne `null`, et il ne faut pas inventer un 200. Après déploiement futur explicitement approuvé du correctif, les événements POST enregistreront ce statut sans révéler le corps. Le filtre ne déclenche aucun appel et aucun paiement.

## Validation

Les tests utilisent des clés, jetons, coordonnées et réponses **fictifs**. Les nouveaux cas couvrent FR/EN, longueur de référence, trois formes de succès déjà prises en charge, erreurs métier HTTP 200, erreurs HTTP, JSON invalide/non objet, timeout, URL invalide, absence de jeton, non-divulgation des journaux et extraction minimale.

La suite d'abonnement vérifie notamment CDF, USD, remise annuelle de 20 %, retours/webhooks, doublons, absence d'activation sur erreur et rollback d'initialisation. Une assertion historique qui exigeait de conserver un texte libre du prestataire dans les logs est adaptée au nouveau schéma sûr. Le test de paiement manuel reçoit un taux fictif explicite pour supprimer sa dépendance à une API de change.

Le premier passage du 24 novembre a utilisé PostgreSQL 18.7 car Docker Desktop ne démarrait pas. Ses 96 tests réussis sont un résultat historique, **pas une validation PostgreSQL 14 ni une équivalence de production**.

Le 25 novembre, les binaires portables PostgreSQL **14.24** sont récupérés depuis [l'archive officielle distribuée par EDB](https://get.enterprisedb.com/postgresql/postgresql-14.24-1-windows-x64-binaries.zip), sans installation système ni service Windows. L'archive passe le contrôle CRC ZIP ; SHA256 local : `7d49a448d8bda9bb56febd44f57b9cebfe8e9728428334bd25475cbc860ed969` (empreinte calculée, pas comparaison à une signature éditeur). Un cluster jetable SCRAM sur 127.0.0.1 et port libre est utilisé avec base et utilisateur distincts. `SHOW server_version` confirme 14.24. Les requêtes HTTP non simulées passant par requests sont bloquées par le runner. Les médias du passage complet sont temporaires. Les clusters sont arrêtés et supprimés après les passages.

### Contrat officiel et références historiques

Source officielle figée au commit `d57291d0d2e108a96d6422e6a747f420907bdf0e` : [validation.py, ligne 96](https://github.com/cinetpay/cinetpay-python/blob/d57291d0d2e108a96d6422e6a747f420907bdf0e/src/cinetpay/validation.py#L96). SHA256 du fichier téléchargé : `9d109a9a59818c7099b35fe471d5bb3dbda66b307fff3a8a8d9b101f90662815`. Le code AST confirme l'appel `_assert_string("merchant_transaction_id", ..., 1, 30)`. Le helper officiel et sa classe ValidationError sont exécutés localement sans importer un client réseau : **30 caractères acceptés, 31 et 36 refusés**. Cela prouve la limite du validateur officiel, sans prouver à lui seul la réponse du serveur lors de l'incident.

Quatre tests de base de données supplémentaires comparent **toutes les colonnes** d'une transaction fictive portant une référence historique de 36 caractères avant/après :

- `test_generating_new_references_never_updates_existing_transactions` : nouvelles références à 30, zéro requête SQL du générateur, ancienne ligne strictement identique.
- `test_resume_keeps_historical_reference_and_entire_transaction_unchanged` : même demande reprise, aucune nouvelle initialisation, référence complète et ligne inchangées.
- `test_status_check_uses_full_historical_reference_without_database_update` : requête simulée de vérification portant la référence entière, aucune troncature et ligne inchangée.
- `test_authenticated_notification_matches_full_historical_reference` : notification authentifiée simulée retrouvant la demande par la référence entière, ligne inchangée pendant la vérification.

Aucune migration, commande de reprise ou réécriture de données n'est ajoutée. Seul le générateur des futures références change. Le traitement normal des statuts par les services existants est conservé ; aucun paiement historique n'est consulté sur une base réelle.

### Journaux, prix et contrôles

`test_all_log_levels_exclude_secrets_payloads_and_customer_data` capture les journaux du fournisseur dès DEBUG avec clés, mot de passe, jeton, email, téléphone, nom client, URL de session et texte libre fictifs à la racine et dans des objets imbriqués. Aucune de ces valeurs n'est présente dans les événements capturés. Les autres tests couvrent aussi le refus HTTP/métier, le JSON invalide, l'URL absente/invalide, l'erreur réseau et le filtre historique. Les appels de journalisation du module sont relus : seules des métadonnées explicitement autorisées sont émises, aucun payload brut ni exception réseau libre.

Un contrôle supplémentaire des **107 lignes du fournisseur** dans la trace du dernier passage complet trouve zéro occurrence des marqueurs privés fictifs recherchés. Ce contrôle complète les assertions DEBUG ; il ne porte pas sur les anciens journaux du VPS. Aucun répertoire de cluster PostgreSQL 14 temporaire ne subsiste après les tests.

Les fichiers `core/services/subscription.py`, `joatham_users/models.py`, `core/models.py` et `joatham_pro/settings.py` sont identiques à HEAD. Les tests existants vérifient notamment un forfait fictif de 10 USD/mois, 96 USD/an (12 mois moins 20 %), l'impossibilité d'imposer un montant client et la conversion en CDF. Aucun tarif, forfait, taux de réduction ou configuration de paiement n'est modifié. Le premier passage des 944 tests a révélé un autre ancien test d'estimation dépendant d'un taux externe : seule sa fixture dans `joatham_users/tests.py` est rendue explicite (CDF, taux fictif 2300), avec une assertion renforcée à 112700 CDF pour son prix fictif existant de 49 USD. Aucun code de conversion de production n'est changé.

| Cas demandé | Test / preuve |
| --- | --- |
| Maximum officiel de 30 | Helper officiel exécuté sur 30, 31 et 36 ; `test_reference_fits_documented_limit_without_changing_prefix` |
| Références historiques | Les quatre tests `HistoricalCinetPayReferenceTests` ci-dessus, avec comparaison intégrale des lignes |
| Refus métier HTTP 200 | `test_http_200_business_error_is_not_reported_as_missing_url` (FR/EN), `test_cinetpay_http_200_business_error_rolls_back_without_activation` |
| URL absente | `test_missing_url_diagnostic_never_logs_payload_or_free_text` et test de rollback existant dans `SubscriptionPaymentTests` |
| Sandbox .net | `test_sandbox_domain_is_not_misclassified_as_production` : .net Sandbox, .co production |
| Aucun secret/client/payload en journal | `test_all_log_levels_exclude_secrets_payloads_and_customer_data` et cas de refus, erreurs et filtre |
| Tarifs et remise | Tests mensuels/annuels et devise existants de `SubscriptionPaymentTests`, fichiers métier identiques à HEAD |

Résultats du 25 novembre :

| Contrôle | Environnement | Résultat |
| --- | --- | --- |
| Tests ciblés CinetPay/abonnements et estimation hors réseau | PostgreSQL 14.24, Windows, Python 3.14.10, Django 6.0.10 | **102 réussis**, 19,246 s |
| Suite Django complète | Même PostgreSQL 14.24 isolé, HTTP via requests bloqué | **944 réussis**, 309,013 s ; zéro erreur/échec au passage final |
| Tests JavaScript de la CI | Node 24.22.3 local | **6 réussis** |
| Compilation FR/EN, `check_translations --extract`, `git diff --exit-code -- locale` | gettext local | Réussis ; catalogues identiques |
| `pip check` | Venv local existant | Aucune dépendance cassée |
| `git diff --check` | Worktree local | Réussi |
| Étape Nginx Linux de la CI | Docker Desktop indisponible ; seule distribution WSL docker-desktop, pas de runner Ubuntu disponible | **Non exécutée pour ce diff** |
| Job GitHub Actions | Workflow déclenché sur pull_request, diff non publié | **Non déclenché** ; aucun résultat CI distant revendiqué |

La reproduction locale ne constitue pas une CI complète verte : il manque un environnement Linux fonctionnel (Ubuntu 22.04 avec Nginx et ses fonctions de liens symboliques) pour l'étape Nginx. Les tests Django natifs Windows sur PostgreSQL 14.24 ne sont pas présentés comme une exécution du job Ubuntu. Aucun commit, push, fusion ou déploiement n'est réalisé ; le diagnostic et le diff restent destinés à la revue préalable.

Le passage initial de 944 tests avait une erreur dans le test d'estimation sans taux hors réseau ; le passage final ci-dessus est relancé après ajout de sa fixture, avec toutes les assertions métier conservées et renforcées. Les fichiers Nginx et le workflow CI sont identiques à HEAD. Les journaux réels du VPS n'ont pas été inspectés ni nettoyés : les garanties de non-divulgation vérifiées concernent le code proposé et les journaux fictifs des tests, pas une certification des anciens journaux de production.
