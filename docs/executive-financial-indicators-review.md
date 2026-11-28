# Tableau de bord exécutif — audit et proposition locale

Branche `codex/dashboard-financial-indicators`, issue de `main` à `6f8ef54`.
Aucun accès au VPS, aucune donnée réelle, aucun appel de paiement, aucune fusion ni mise en production.
Les aperçus et règles de calcul ont été validés par l'utilisateur pour publication d'une PR en brouillon.

## Fonctionnement avant modification

L'examen initial a porté sur `Facture`, `PaiementFacture`, `PaymentTransaction`, leurs services et le sélecteur partagé du tableau de bord. Aucun modèle ni service métier n'a été modifié pendant cet audit.

| Indicateur | Calcul initial | Périmètre et date |
| --- | --- | --- |
| Chiffre d'affaires | Somme du champ `Facture.montant`, alimenté avec le total HT des lignes avant les réductions | Toutes les factures de l'entreprise, brouillons et annulations compris ; aucun filtre de période |
| Encaissements | Somme de `Facture.total_paye`, qui retient les `PaiementFacture` au statut `valide` | Tous les paiements des factures de l'entreprise, sans filtre de date de paiement ; ni encaissements libres ni remboursements |
| Factures payées | Nombre de factures dont le booléen `paye` vaut vrai | Toutes les factures de l'entreprise ; aucun recalcul du solde |
| Petites barres des cartes | Dix éléments HTML dont les hauteurs sont fixées par CSS | Décoration sans données financières |
| Graphique circulaire | Comptages `paye=True/False` du sélecteur | Données réelles, mais héritant de la sélection et du booléen précédents |

`Facture.date` est une date de **création automatique**, pas une date d'émission distincte. Le modèle ne possède pas de date d'émission dédiée. `PaiementFacture.date_paiement` et `PaymentTransaction.transaction_date` sont distincts de leur date de création et de validation.

Les vues existantes prennent l'entreprise depuis l'utilisateur authentifié, sous les décorateurs de permission et d'accès au module. Le sélecteur de factures limite déjà les factures à cette entreprise. Le nouveau reporting conserve ces protections et filtre également l'entreprise des paiements ainsi que celle de leur facture, y compris pour des liaisons historiquement incohérentes.

Le module Paiements distingue encaissement, décaissement, remboursement et ajustement. Une confirmation liée à une facture crée un `PaiementFacture` et en garde la référence : additionner aveuglément les deux tables doublerait le montant. Les remboursements sont des sorties confirmables mais les services n'autorisent pas leur liaison à une facture. Aucun modèle d'avoir n'a été trouvé.

## Cas 353 125 CDF / zéro facture payée

Ce résultat est **normal pour un paiement partiel**. Une facture de 500 000 CDF réglée à hauteur de 353 125 CDF produit zéro facture entièrement soldée et un reste de 146 875 CDF. Ce cas est reproduit en test, en FR/EN.

Une autre cause possible est un booléen historique désynchronisé. Le nouveau compteur calcule le solde à partir des paiements validés et retrouve une facture soldée même si `paye=False`. Il ne réécrit ni le statut ni le booléen. Un statut déclaré payé sans paiement enregistré ne suffit inversement plus à afficher une facture financièrement soldée.

Nous n'avons pas examiné les lignes réelles de l'exemple : le test prouve la cohérence possible au vu des modèles, pas la cause exacte de cet enregistrement en production. L'affichage des paiements partiels, des encaissements bruts et des remboursements permet de distinguer les situations.

## Règles de reporting proposées

- **Période** : tout l'historique par défaut, pour ne pas introduire un filtre mensuel implicite ; bornes facultatives inclusives dans le fuseau Django actif. Les dates invalides donnent une réponse 400 avec explication, sans indicateurs non filtrés de repli.
- **CA facturé** : factures actuellement `emise` ou `payee`, sélectionnées sur `Facture.date`. Les brouillons et annulations sont exclus. La base existante HT avant remises est conservée et explicitement affichée ; aucune nouvelle règle de prix, de remise ou de TVA n'est appliquée aux documents.
- **Encaissements nets validés** : paiements de factures validés sur `date_paiement`, plus transactions d'encaissement libres confirmées sur `transaction_date`, moins remboursements confirmés sur `transaction_date`. Les représentations liées sont comptées une seule fois, avec priorité au paiement de facture et à sa date. Les attentes, rejets et annulations sont exclus. Un paiement d'une facture d'une autre période ou désormais annulée reste un encaissement reçu tant que le paiement lui-même est valide.
- **Devise** : code de l'entreprise visible ; les transactions explicites dans une autre devise sont exclues et leur nombre est annoncé. Aucun taux courant ou montant estimé n'est mélangé aux montants historiques. Les alias de devise reconnus par le projet sont normalisés.
- **Factures entièrement soldées / non soldées / partielles** : cohorte des factures retenues par leur date de création, avec leur solde **actuel**, calculé à partir de tous leurs paiements validés. Ce n'est pas un état des créances à la date de fin. Ce compteur n'est pas le nombre de paiements reçus pendant la période : la carte d'encaissements affiche désormais ce dernier séparément.
- **Reste à encaisser** : reste actuel de cette cohorte. Dépenses et TVA du résumé financier sont sélectionnées sur la même période ; les dépenses utilisent leur champ `date`. Le calcul simplifié « bénéfice » existant reste CA moins dépenses, et n'est pas un résultat comptable net.
- **Graphiques** : suppression des quatre séries de barres décoratives ; tableau mensuel avec montants lisibles et barres proportionnelles réellement agrégées sur la même période/devise. Les mois comportant des opérations sont affichés. Les valeurs négatives sont libellées et colorées en rouge. Le graphique circulaire utilise les compteurs recalculés de la même cohorte ; ses pourcentages respectent FR/EN.
- **Autres informations** : clients, stock et activité récente restent actuels et sont explicitement signalés hors filtre financier. Les autres tableaux de bord de rôle et les services de facturation/paiement sont préservés.

## Limites et décisions avant mise en production

1. Les avoirs ne sont pas modélisés : aucune déduction automatique fiable n'est possible. Leur prise en charge demanderait un chantier métier distinct.
2. Les factures et paiements de factures ne portent pas leur propre devise historique. Le reporting les exprime dans la devise de l'entreprise conformément au modèle existant ; tout changement passé de devise demande une revue/migration des données avant de considérer le total comme une comptabilité multidevise.
3. Les remboursements du module Paiements sont déduits des encaissements mais ne rouvrent pas le solde d'une facture : aucun lien de rapprochement n'est disponible dans les services actuels. Aucune affectation n'est inventée.
4. Le périmètre du nouveau CA (hors brouillons/annulations, toujours HT avant remises) et l'inclusion des encaissements libres/remboursements ont été validés par l'utilisateur pour revue en PR. Le reporting exécutif est corrigé sans modifier les documents persistés ni les écritures comptables.
5. Les statuts de facture et de paiement sont lus dans leur état actuel : ce rapport ne reconstitue pas un historique d'annulation à la date de clôture. Un véritable bilan « à date » nécessiterait des règles et données complémentaires.

## Contrôles

Tests de régression : cas 353 125/0, drapeau historique erroné, statut payé sans paiement, dates facture/paiement distinctes, brouillons/annulations, paiement d'une facture annulée, dédoublonnage, remboursement, paiements invalides, devises différentes, bornes inclusives et fuseau local, net négatif, autre entreprise, liaison corrompue, montants HT/TVA/remise, séries réconciliées, formulaire invalide, droits des rôles et parcours FR/EN.

Les résultats finaux et aperçus sont consignés dans [la galerie locale](previews/financial-indicators/README.md). Les fixtures utilisent une base PostgreSQL 14.24 temporaire sur `127.0.0.1` et des données fictives. Les appels HTTP des tests sont bloqués ou simulés ; aucun paiement réel n'est exécuté.
