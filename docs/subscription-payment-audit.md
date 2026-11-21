# Abonnement et paiement : audit et validation

Périmètre : branche issue de `main` à `187e94d`. Aucun accès au VPS, paiement réel, changement de prix, forfait, durée ou remise annuelle (20 %). Les constatations de sécurité ont été présentées avant les modifications. Les réglages de production ne sont pas déduits de ceux du poste local.

## Parcours et sources

| Étape | Code et règle existante |
| --- | --- |
| Choix du forfait | `core/views.py:subscription_plan_list`, intentions publiques dans `core/services/subscription_intents.py` ; prix serveur, référence USD, remise annuelle existante |
| Déclaration hors plateforme | `PaiementAbonnementForm`, `create_subscription_payment_request` ; référence, téléphone, justificatif ; validation manuelle du super admin |
| Paiement hébergé | `core/services/payment_providers.py:CinetPayPaymentProvider`, `core/services/subscription_payments.py` ; création de session puis redirection |
| Stockage | `PaiementAbonnement` (références uniques, montant attendu, devise, états, preuve, dates), `IntentionAbonnement`, `AbonnementEntreprise` |
| Notification | `subscription_payment_webhook` ; v1 : comparaison constante du notify_token puis consultation authentifiée du statut ; ancien Checkout v2 : HMAC et site marchand puis consultation serveur |
| Confirmation | contrôle montant, devise, référence et identifiant de transaction ; activation/prolongation dans une transaction |
| Retour navigateur | recherche limitée à l'entreprise ; les paramètres du navigateur ne prouvent jamais un paiement |
| Traces | événements d'audit existants et historique des paiements ; pas de nouvel événement persisté nécessitant un libellé supplémentaire |

**CinetPay et Mobile Money ne sont pas deux prestataires intégrés distincts.** CinetPay est le prestataire automatique. Mobile Money est un moyen de paiement qui peut être offert sur sa page hébergée, selon les habilitations du marchand. Le parcours hors plateforme permet aussi de déclarer un transfert Mobile Money, carte, virement, espèces ou autre paiement manuel. Il ne déclenche aucun prélèvement.

`CINETPAY_CHANNEL` pilote PUSH/OTP/QRCODE. Le paramètre `CINETPAY_CHANNELS=MOBILE_MONEY` existe mais n'est pas envoyé par le client API v1 actuel : il ne prouve donc pas la liste des moyens effectivement proposés. Aucun opérateur ni bénéficiaire n'est inventé par cette modification.

Réglages locaux inspectés sans afficher de secret : paiement automatique désactivé, prestataire et devise non configurés, aucune clé ni URL de retour/notification configurée. `JOATHAM_PAYMENT_SANDBOX=True` **ne sélectionne pas à lui seul un environnement de test** ; les URL par défaut sont celles de l'API CinetPay. Tous les appels des tests sont simulés.

## Défauts et corrections

| Constat | Correction |
| --- | --- |
| Même identifiant de transaction pour notification en attente puis succès : succès considéré à tort comme doublon | Déduplication selon l'état ; la progression en attente → payé reste possible |
| Notification tardive pouvant déclasser un succès et permettre une nouvelle prolongation | Succès irréversible ; les données financières confirmées restent immuables |
| Devise reçue écrasant la devise attendue avant le contrôle | La devise attendue et le montant payé ne sont pas remplacés par un résultat rejeté |
| Validation manuelle depuis un objet périmé, ou d'un paiement automatique non vérifié | Relecture verrouillée ; validation/refus manuels exclus pour les paiements automatiques, y compris dans les formulaires d'administration |
| Risque de courses entre notifications/renouvellements | Verrou entreprise avant paiement/intention ; transaction atomique, contrôle des identifiants uniques ; test de notifications simultanées PostgreSQL |
| Clics répétés créant plusieurs sessions | Réutilisation de la session en attente pour la même entreprise, le même forfait, la même période et le même prestataire ; montant enregistré conservé |
| Renouvellement automatique du même plan bloqué | Autorisé avec récapitulatif ; aucune activation avant confirmation ; période achetée calculée depuis la fin précédente |
| Redirection directe, sans total réel dans la devise de facturation | Récapitulatif interne avant la page hébergée, y compris après inscription/connexion ; prix USD séparé du total de session |
| Échec/expiration/annulation confondus avec attente ; message technique brut | Messages FR/EN dédiés ; état « à vérifier » pour incohérence ; ne pas repayer en cas de débit et fournir la référence au support |
| Absence de rattrapage si notification retardée | POST protégé CSRF et limité à l'entreprise, consultation authentifiée CinetPay puis mêmes contrôles d'activation ; aucune confiance dans un statut fourni par le navigateur |
| Historique limité aux huit derniers événements | Historique paginé, détail durable, référence, période couverte, montant confirmé et impression de la confirmation ; une demande de plan n'est pas présentée comme une preuve de paiement |
| Justificatif lié directement au stockage depuis l'administration | Téléchargements applicatifs authentifiés propriétaire/super admin, pièce jointe, sans cache ; l'accès direct au stockage reste un prérequis d'exploitation à contrôler |
| Session v1 sans jeton de notification | Pas de redirection vers une session incapable de recevoir une confirmation authentifiée |
| Langue de paiement CinetPay figée en français | Langue FR/EN transmise selon la langue active |

## Décisions et prérequis avant production

1. **Compte CinetPay** : faire confirmer les pays, devises, opérateurs, moyens et éventuels frais réellement activés. Valider les URL HTTPS de notification/retour et les clés avec le prestataire. Ne pas utiliser le seul drapeau sandbox comme garantie d'absence de paiement réel.
2. **Paiements manuels** : valider la liste des bénéficiaires/numéros par opérateur et devise, les responsabilités du rapprochement, le canal de support et le délai de traitement à annoncer. En attendant, le formulaire demande une confirmation des coordonnées par l'équipe ; aucun numéro de support n'est présenté comme un numéro à payer.
3. **Justificatifs privés** : vérifier Nginx/stockage et interdire l'accès public direct à `abonnements/preuves/`. La protection des nouvelles routes ne suffit pas si `/media/` sert encore les fichiers directement. Aucune modification du VPS dans ce chantier.
4. **Changement de plan** : les règles existantes sont conservées : activation immédiate du plan après paiement et prolongation depuis la fin existante, sans proratisation nouvelle. Faire valider cette règle commerciale avant mise en ligne.
5. **Incidents de création de session** : un timeout réseau reste ambigu côté prestataire et la transaction locale de création est annulée. Ne pas affirmer qu'un débit a eu lieu ou non ; rapprocher le journal marchand avant de relancer si le client signale un débit. Une garantie inter-systèmes en cas de timeout nécessiterait une clé d'idempotence documentée par CinetPay ou une évolution persistante dédiée.
6. La confirmation livrée est consultable et imprimable dans l'application. Une confirmation additionnelle par email, avec file d'envoi fiable, peut être décidée séparément ; aucun email ni SMS réel n'est envoyé par les tests.

## Vérification

- Contrôle Django sans accès à une base, extraction et compilation GNU gettext 0.21 des catalogues FR/EN, domaines django/djangojs.
- Régressions : progression avec même identifiant, succès puis notification contradictoire, devise incorrecte puis correction, objet périmé en validation manuelle, exclusion des validations automatiques manuelles, session réutilisée, remise annuelle 20 %, renouvellement, consultation serveur et isolation entre entreprises.
- Rendus FR/EN et absence de `None` ; captures locales avec données fictives, sans aucun lien de paiement suivi. Les captures ne prouvent pas la disponibilité d'un opérateur réel.
- Docker local indisponible : aucune substitution par SQLite. Les tests de base et de concurrence sont destinés au PostgreSQL 14.24 isolé de la CI du projet ; compléter ici le résultat constaté avant validation.

Processus : LOCAL → TEST → COMMIT → VALIDATION → MERGE → PROD. La revue est préparée en brouillon ; fusion et déploiement restent soumis à l'accord de l'utilisateur. Aucun workflow de déploiement n'est modifié.
