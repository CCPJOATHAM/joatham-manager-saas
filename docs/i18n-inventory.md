# Inventaire FR/EN et vérifications

L'audit de départ a parcouru les templates, les textes Python et le JavaScript de tous les modules. Il a trouvé 2 804 fragments de templates candidats non marqués, 677 occurrences marquées sans traduction anglaise, 1 502 littéraux Python candidats et 20 fragments JavaScript à examiner. Ces nombres sont des résultats de détection : ils incluent des doublons et des faux positifs techniques, et ne représentent pas un nombre d'écrans.

| Zone | Lacunes constatées en anglais | Traitement |
| --- | --- | --- |
| Tableaux de bord propriétaire, gestionnaire, comptable | Indicateurs, synthèses, alertes, pluriels, actions rapides | Catalogue anglais, phrases avec compteur et libellés traduits |
| Clients, factures, proformas, services | Formulaires, statuts, paiements, confirmations, tickets et PDF | Django i18n et catalogue JavaScript |
| Caisse et paiements | Sessions, écarts, validations, filtres et exports | Libellés, validations Python et en-têtes traduits |
| Produits et inventaires | Comptage, mouvements, ruptures et alertes | Traductions HTML/Python/JavaScript et exports |
| Comptabilité | Bilan, résultat, balance et grand livre | Contextes comptables pour Actif/Passif/Produits/Charges |
| Apprenants et formations | Inscriptions, soldes, reçus et quittances | Templates, validations et PDF traduits |
| Ressources humaines | Employés, présences, congés, salaires et documents | Formulaires, notifications, rapports et CSV traduits |
| Messagerie et invitations | Validations, sujets et corps d'emails, réponses et notifications | Textes système traduits ; messages saisis conservés |
| Plateforme et abonnements | Administration, maintenance, taux de change, plans et paiements | Templates, formulaires, notifications et navigation traduits |
| Pages publiques et compte | Métadonnées, connexion, inscription, mot de passe et profil | FR/EN, catalogue JS et persistance vérifiée |

Les catalogues contiennent 3 080 entrées Django et 15 entrées JavaScript par langue, sans entrée active vide ni fuzzy. Les catalogues français existants sont conservés et complétés. Le remplissage anglais a utilisé une traduction locale assistée, suivie de corrections de vocabulaire métier, des pluriels, des paramètres et des parcours principaux. Une revue éditoriale des formulations dans les écrans reste utile dans la PR.

Les noms d'entreprises, personnes, produits, descriptions, observations et messages saisis ne sont pas traduits. Les codes des statuts, rôles, monnaies et interfaces externes restent stables. Aucun changement de schéma n'est ajouté.

Les tests bilingues vérifient les pages des modules, les tableaux de bord selon le rôle, le profil après reconnexion, les cookies, le catalogue JavaScript, une saisie de client en français pendant une navigation anglaise et les libellés/données d'une facture PDF. Le contrôle de catalogue vérifie aussi les paramètres de formatage et peut comparer l'extraction des sources avec les catalogues via `check_translations --extract`.

Le banc est exclusivement local : Ubuntu 22.04 amd64, Python 3.14.10, dépendances épinglées du projet et PostgreSQL 14.24. Les bases `test_joatham_i18n*` sont créées puis supprimées par Django. Le hachage MD5 est activé uniquement par le lanceur des tests. Aucun accès au VPS, aucune fusion et aucun déploiement ne sont effectués.

La règle durable est définie dans `AGENTS.md`, détaillée dans `docs/i18n.md`, reprise dans le modèle de PR et contrôlée par le workflow `Interface FR EN`, déclenché uniquement sur les demandes de fusion.

Les événements système connus sont traduits à l’affichage, y compris les descriptions françaises historiques reconnues. Les notes libres et les données persistées restent intactes. Les dates d’interface suivent les formats localisés de Django.

Les événements système connus sont traduits à l'affichage, y compris lorsqu'ils ont été enregistrés avant cette PR. Les descriptions et métadonnées stockées restent inchangées ; un texte libre non reconnu reste dans sa langue d'origine.

Validation finale : 826 tests réussis sur PostgreSQL 14.24 local, dont 12 tests i18n ; extraction des sources, compilation des quatre catalogues, paramètres de formatage et absence de migration vérifiés. Les avertissements xhtml2pdf sur certaines propriétés CSS restent ceux du moteur PDF existant.
