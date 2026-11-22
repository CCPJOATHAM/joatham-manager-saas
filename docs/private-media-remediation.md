# Correctif des médias privés — dépendance de la PR #41

## Risque confirmé et périmètre

L'opérateur a confirmé deux blocs `location /media/` avec un alias vers `/home/joatham/apps/joatham_saas/media/`, dans `/etc/nginx/sites-enabled/default` et `/etc/nginx/sites-enabled/joatham`. Ces réponses contournent Django. Le verrou d'entreprise ne peut donc pas garantir la confidentialité tant que ces routes publiques existent.

Cette PR distincte est basée sur `codex/company-deletion-workflow` (PR #41), dont elle utilise le verrou persistant. Elle ne fusionne pas la PR #41. Aucun accès au VPS ou aux données réelles, aucune modification Nginx effective, aucun déplacement ou effacement de fichier n'est effectué.

## Solution préparée

Les fichiers restent dans leur stockage existant pour préserver les références historiques. Le serveur Django lit le fichier seulement après autorisation de l'objet ; il n'émet aucune redirection vers `FieldFile.url`.

| Usage | Route applicative / contrôle | Accès direct au stockage prévu |
| --- | --- | --- |
| Justificatif de paiement | `payment_attachment` : connexion, permission `payments.view`, module `payments`, entreprise active et sans demande en attente, objet de cette entreprise | Refusé |
| Preuve d'abonnement | `subscription_payment_evidence` : permission `subscription.view`, entreprise et objet ; route administrative distincte `subscription_payment_evidence_admin` avec permission super-admin | Refusé |
| Pièce jointe de messagerie | `message_attachment_download` : permission et module, entreprise active et sans demande en attente, participant de la conversation et entreprise de celle-ci | Refusé |
| Photo de profil | `own_profile_photo` : utilisateur connecté, sa propre photo uniquement ; contrôle d'accès à son entreprise si rattaché | Refusé |
| Logos d'entreprise | URL existante sous `/media/entreprises/logos/` | Public, choix explicite ; aucun document privé ne doit être placé dans ce dossier |
| Logo officiel JOATHAM / visuels statiques | Ressources statiques existantes | Inchangé |

Les réponses privées portent `Cache-Control: private, no-store` et `X-Content-Type-Options: nosniff`. Les documents sont téléchargés en pièce jointe ; seule la photo de profil est affichée dans la page. Un fichier absent produit un 404. La consultation administrative autorisée d'une preuve d'abonnement reste disponible pour la conservation et la revue ; le blocage de l'entreprise ne révoque pas les droits propres du super-administrateur de plateforme.

L'inventaire a couvert les cinq champs `FileField`/`ImageField`, les références `.url`, `MEDIA_URL`, `/media/`, templates, Python, JavaScript, CSS et champs de formulaire. Le lien brut du justificatif et l'image de profil ont été remplacés. Les widgets de modification de profil et de pièces jointes dans Django admin utilisent également les routes autorisées, en conservant les contrôles de remplacement/effacement du champ. Les seules URL de fichiers conservées comme publiques dans les templates et le service de profil d'entreprise concernent les logos. Les champs privés conservent techniquement une propriété de stockage `.url` : elle ne constitue plus une route de lecture autorisée, et Nginx doit la refuser.

En développement, la route générale de service de `MEDIA_ROOT` a été supprimée. Seul le sous-dossier des logos est servi, avec vérification des chemins et des liens symboliques. Le mode `DEBUG` n'expose donc plus les justificatifs, messages ou photos.

## Configuration à appliquer ultérieurement, après validation explicite

Le fragment versionné est `deploy/nginx/media-access.conf`. Il choisit le téléchargement par Django : aucune zone `internal`, aucun jeton de stockage ni `X-Accel-Redirect` n'est nécessaire dans cette version.

**Le commit applicatif seul ne corrige pas le VPS.** Les deux sites doivent remplacer leur ancien bloc `/media/` par ce fragment. Il faut aussi examiner tous les autres hôtes/ports, sites HTTP/HTTPS, serveur par défaut, règles regex, alias, racines, liens symboliques, CDN et chemins alternatifs qui pourraient encore exposer le stockage. Une configuration supplémentaire ou un autre stockage exige une adaptation revue. Les exemples utilisent le chemin confirmé par l'opérateur ; ne pas recopier le chemin différent de `.env.production.example`.

Pour la future intervention autorisée :

1. Sauvegarder les configurations Nginx avec des permissions privées, relever les hôtes et le `MEDIA_ROOT` effectifs, examiner les liens symboliques. Vérifier que les médias publics se limitent bien aux logos et aux ressources statiques. **Arrêt si une autre ressource légitimement publique est découverte** : définir une exception explicite sans élargir l'accès aux dossiers privés.
2. Préparer la version applicative corrigée et la configuration des deux sites dans une fenêtre coordonnée. Appliquer la restriction Nginx avant de déclarer la confidentialité rétablie ; les anciens liens de documents peuvent momentanément être refusés jusqu'à l'activation des nouvelles vues. Ne pas rétablir un alias public pour résoudre ce refus.
3. Valider la configuration complète avec `nginx -t` ; **arrêt en cas d'erreur**. Recharger Nginx seulement après autorisation et validation. Examiner ensuite la configuration effective pour tous les sites ; les tests du fragment isolé ne prouvent pas la priorité des règles sur le VPS.
4. Activer la version applicative selon la procédure de déploiement validée. Ce correctif ne comporte aucune migration ni conversion de fichiers. Vérifier les vues de téléchargement et l'affichage des logos.
5. Contrôler avec des données fictives dans un environnement autorisé : accès anonyme et interentreprises refusés, propriétaire autorisé, permissions/module respectés, entreprise suspendue ou en attente refusée même avec une ancienne URL/session, super-admin autorisé uniquement sur sa route dédiée. Contrôler GET et HEAD des anciens chemins privés, chemins encodés et hôtes alternatifs. Ne pas utiliser de document réel pour une démonstration.
6. Vérifier l'absence de cache public de documents et traiter les caches CDN existants, si présents, selon une procédure autorisée. Un fichier déjà téléchargé ne peut pas être rappelé. Des URL signées externes restent un problème distinct de révocation : ne pas supposer qu'une expiration future équivaut à un blocage immédiat.

**Retour arrière :** conserver le refus Nginx des médias privés même en cas de retour à une ancienne version applicative. Ce choix peut rendre les anciens boutons inopérants jusqu'au redéploiement du correctif ; il évite de rouvrir les documents. Ne supprimer, déplacer ou renommer aucun fichier pendant ce retour arrière.

## Contrôles reproductibles

- Django : `python manage.py test core.test_private_media core.test_company_deletion joatham_payments joatham_messages` avec la configuration du projet et une base PostgreSQL de test distincte. Les nouveaux tests utilisent un `MEDIA_ROOT` temporaire et des contenus fictifs exclusivement ; ils vérifient FR/EN, anonymes, autre entreprise, participant, blocage persistant, suspension, accès aux logos, chemins, photo et liens de formulaire.
- Nginx Linux : `python tests/nginx/check_private_media.py`. Le script démarre uniquement un processus Nginx isolé sur `127.0.0.1` et un port libre, avec configuration et fichiers fictifs temporaires ; il n'utilise pas `/etc/nginx`, ne relance aucun service et ne lit aucun document utilisateur. Six tests couvrent les quatre catégories privées, un futur dossier privé, GET/HEAD, traversées, regex, symlink, logos publics et interdiction de l'indexation/écriture HTTP.
- CI : le job de PR installe Nginx comme outil de test et exécute ces six contrôles, puis les contrôles de catalogues et la suite Django sur PostgreSQL 14.24. Aucun déploiement n'est ajouté.

Les résultats exacts et le SHA contrôlé sont consignés dans la PR avant demande de validation. La protection de production reste à appliquer après accord ; elle n'est pas attestée par les tests locaux.

Résultats locaux du 22 novembre 2026 : **84 tests Django réussis** en 131,497 s, dont 15 nouveaux tests de confidentialité, sur PostgreSQL **14.24** (conteneur jetable, port `127.0.0.1:55440`, base `test_joatham_deletion_tests`, Python 3.14.10). **Six tests Nginx réussis** dans un conteneur Ubuntu local avec le dépôt monté en lecture seule. Le contrôle CI des catalogues a été reproduit : compilation FR/EN, `check_translations --extract`, puis `git diff --exit-code -- locale`, tous réussis. Aucun texte traduit nouveau n'est introduit ; les catalogues compilés restent identiques. `git diff --check` ne signale aucune erreur.
