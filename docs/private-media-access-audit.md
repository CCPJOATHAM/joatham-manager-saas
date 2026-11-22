# Accès aux fichiers après blocage d'une entreprise

Audit du 22 novembre 2026 sur la branche `codex/company-deletion-workflow`. Analyse du code et des configurations suivies uniquement : aucun accès au VPS, aucune lecture de fichier utilisateur, aucun appel HTTP de production, aucune modification des données ou de la configuration d'exploitation.

## Conclusion avant fusion

**Mise à jour après retour de l'opérateur :** la présence des deux alias publics `/media/` a été confirmée sur le VPS. Le correctif préparé est décrit dans [la revue de remédiation](private-media-remediation.md). Les constats de code ci-dessous décrivent l'état initial audité ; les liens privés et le service de développement ont depuis été corrigés dans cette branche. Les alias du serveur n'ont pas été modifiés.

**Le blocage du compte ne garantit pas le blocage des URL des fichiers.** Une réponse fournie par Nginx, un CDN ou un stockage public ne traverse pas le middleware Django. Un ancien lien connu peut donc rester utilisable si son stockage est public. Un nom UUID réduit la découverte ; il ne constitue pas une autorisation.

Le dépôt démontre ce risque architectural. Aucune configuration Nginx effective ni politique de stockage de production n'est versionnée. L'opérateur a confirmé les alias vers `/home/joatham/apps/joatham_saas/media/` dans les deux sites (`default` et `joatham`). Leur configuration complète et leur priorité restent à relire avant intervention. **La confidentialité des médias privés en production reste un point bloquant tant que la restriction Nginx n'est pas effectivement appliquée et contrôlée.**

## Chemins et contrôles observés avant correctif

`joatham_pro/settings.py` définit `MEDIA_ROOT` par `DJANGO_MEDIA_ROOT` (défaut : `BASE_DIR / "media"`) et `MEDIA_URL` par `DJANGO_MEDIA_URL` (défaut : `/media/`). Aucun backend personnalisé `STORAGES` ou `DEFAULT_FILE_STORAGE` n'est défini dans ces réglages : le stockage Django par défaut est le système de fichiers. Cela ne prouve pas la configuration réellement chargée par le service. L'exemple `.env.production.example` utilise encore un autre chemin, `/home/joatham/apps/joatham_pro/media` : ne pas le recopier sur le VPS sans vérifier le chemin effectif.

| Fichier / source | Chemin relatif au stockage | Accès trouvé / limite |
| --- | --- | --- |
| Justificatif de paiement, `joatham_payments/models.py`, `PaymentTransaction.attachment` | `payments/supporting_docs/` | `payment_detail.html` utilise directement `payment.attachment.url`. Aucune autorisation Django à la lecture de cette URL si elle est servie publiquement. |
| Preuve d'abonnement, `core/models.py`, `PaiementAbonnement.preuve_paiement` | `abonnements/preuves/` | Vues `subscription_payment_evidence` (entreprise et permission) et `subscription_payment_evidence_admin` (permission super-admin), réponse privée `no-store`, `nosniff`. Un alias public vers le même fichier contourne ces contrôles. |
| Pièce jointe de messagerie, `joatham_messages/models.py`, `MessageAttachment.fichier` | `messages/entreprise_ID/conversation_ID/UUID.extension` | Vue `download_attachment`, permission/module et sélection par entreprise **et** participant. La réponse actuelle ne définit pas explicitement `private, no-store`. Le chemin physique peut contourner la vue s'il est public. |
| Logo d'entreprise, `joatham_users/models.py` | `entreprises/logos/` | URL directe utilisée par les paramètres d'entreprise et le profil d'entreprise. Décider explicitement de son caractère public, indépendamment des pièces privées. |
| Photo de profil, `joatham_users/models.py` | `profiles/` | URL directe dans le profil ; donnée personnelle dont la politique de visibilité doit être définie. |

L'inventaire des `FileField` / `ImageField` des modèles applicatifs a trouvé ces cinq champs. Le modèle `DocumentRH` n'apporte pas la preuve d'un fichier binaire stocké par un de ces champs : ne pas présenter les documents RH comme une exposition binaire constatée. Les PDF/exports générés par des vues ne sont pas, de ce seul fait, des fichiers publics persistés. Les sauvegardes et copies externes restent hors de ce constat.

`CompanyDeletionAccessMiddleware` refuse les requêtes d'utilisateurs authentifiés rattachés à une demande en attente. Les requêtes anonymes poursuivent le routage normal. Avec `DEBUG=True`, `joatham_pro/urls.py` ajoute le service direct de `MEDIA_ROOT` : il ne faut donc pas utiliser ce mode pour garantir la confidentialité des médias. En production, `DEBUG=False` retire cette route Django, mais ne retire aucun alias Nginx.

## Vérifications VPS strictement en lecture seule

À exécuter par l'opérateur, une ligne à la fois. Ces commandes ne mettent à jour aucun dépôt, ne chargent pas Django, ne lancent aucune migration et ne relancent aucun service. Ne pas afficher `/proc/.../environ` en entier, les fichiers `.env`, les options complètes d'un backend ou la sortie brute de `nginx -T` : ils peuvent contenir des secrets. Relire et masquer domaines privés, chemins personnels et éventuels paramètres sensibles avant partage.

1. Identifier le service réellement actif, ses fichiers de configuration et son processus :

```bash
systemctl show joatham --no-pager -p ActiveState -p MainPID -p WorkingDirectory -p FragmentPath -p DropInPaths
```

2. Lire seulement les variables pertinentes du processus actif (absence d'une variable = valeur à rechercher dans les réglages chargés, pas preuve d'absence de configuration) :

```bash
p=$(systemctl show joatham -p MainPID --value); if [ "${p:-0}" -gt 0 ]; then readlink "/proc/$p/cwd"; readlink "/proc/$p/exe"; tr '\000' '\n' < "/proc/$p/environ" | grep -E '^(DJANGO_SETTINGS_MODULE|DJANGO_DEBUG|DJANGO_MEDIA_ROOT|DJANGO_MEDIA_URL)='; fi
```

Si `MEDIA_URL` contient une URL signée ou des paramètres, masquer ces paramètres avant partage. Examiner localement le module de réglages indiqué, ses imports et les surcharges de stockage ; ne pas publier leurs secrets. Le dépôt analysé n'utilise pas de stockage objet ; tout backend différent réellement chargé doit faire l'objet d'un contrôle spécifique.

3. Extraire les seules directives Nginx utiles, avec numéros de lignes dans la sortie effective. Aucun rechargement. Un échec de `nginx -T` doit être signalé ; il ne signifie pas qu'aucun alias n'existe.

```bash
sudo nginx -T 2>/dev/null | awk '/^# configuration file / || /^[[:space:]]*(server_name|listen|location|alias|root|internal|auth_request|auth_basic|allow|deny|autoindex|try_files|disable_symlinks)[[:space:];{]/ || /^[[:space:]]*[{}][;]?[[:space:]]*$/ { print NR ":" $0 }'
```

Cette extraction facilite l'inventaire mais n'est pas un parseur complet : les blocs sur une seule ligne et les règles `if`, `rewrite`, `return`, `error_page`, `map`, `proxy_pass`, les includes et modules d'authentification nécessitent une revue locale de la configuration complète. Ne pas conclure à une protection sur la seule absence d'un alias dans l'extrait. Vérifier tous les hôtes/ports, HTTP/HTTPS, serveur par défaut, accès par IP, `/media/`, autres alias, regex et leur priorité. Vérifier que `internal` ou une autorisation effective s'applique au **bloc réellement sélectionné**, sans route alternative publique. `autoindex off` empêche seulement la liste du répertoire ; il ne protège pas un nom connu.

4. Vérifier le chemin réel et les permissions des répertoires, sans lister les fichiers utilisateurs (adapter uniquement si le chemin effectif diffère) :

```bash
readlink -f /home/joatham/apps/joatham_saas/media
```

```bash
namei -l /home/joatham/apps/joatham_saas/media
```

```bash
stat -c '%A %U:%G %n' /home/joatham/apps/joatham_saas/media /home/joatham/apps/joatham_saas/media/payments/supporting_docs /home/joatham/apps/joatham_saas/media/abonnements/preuves /home/joatham/apps/joatham_saas/media/messages
```

Un répertoire absent doit être noté, pas créé. Les permissions Unix ne remplacent pas les autorisations d'entreprise si Nginx peut lire le fichier. Rechercher aussi les liens symboliques et montages configurés vers ce stockage, sans parcourir ou publier les noms des documents.

5. Si stockage objet/CDN constaté : faire vérifier en lecture seule par l'opérateur les accès publics du bucket et des objets, politiques/ACL, identité de l'origine, hôtes alternatifs, cache, durée des URL signées et possibilité de les révoquer après blocage. Une URL signée encore valide peut rester utilisable après révocation de la session. Ne jamais partager de clés, URL signées, jetons ou contenus privés. Sans ces preuves, noter « non vérifié », pas « sécurisé ».

**Aucune requête vers un fichier réel n'est nécessaire à cette inspection.** Un 404 sur un chemin inventé ne prouve rien. Une vérification HTTP avec et sans session ne pourra être faite qu'avec un fichier témoin non confidentiel et une entreprise fictive dans un environnement de test autorisé. Ne pas créer de témoin ni bloquer un compte sur le VPS pendant cette phase en lecture seule.

## Mesures nécessaires, à implémenter dans un chantier revu

- Séparer explicitement les ressources publiques (notamment le logo officiel statique) et les fichiers privés. Interdire les accès HTTP directs à **tous** les préfixes privés, y compris les fichiers historiques et les chemins alternatifs. Éviter un alias public global du stockage mixte.
- Remplacer le lien brut `payment.attachment.url` par une vue de téléchargement authentifiée et limitée à l'entreprise, avec permissions et verrou de suppression. Uniformiser les réponses privées (`Cache-Control: private, no-store`, `nosniff`, téléchargement approprié), notamment en messagerie.
- Servir les fichiers privés par Django ou par une redirection interne Nginx (`X-Accel-Redirect` vers un bloc `internal`) après autorisation. Pour un stockage objet, utiliser une origine privée et une stratégie compatible avec le blocage immédiat ; une URL présignée seule n'offre pas nécessairement cette révocation immédiate.
- Vérifier les caches/CDN et copies déjà remises ; un blocage ne peut pas rappeler une copie déjà téléchargée. Préserver les fichiers et les obligations de conservation : sécuriser leur accès ne signifie pas les supprimer.
- Tester sur données fictives : propriétaire actif autorisé, anonyme refusé, autre entreprise refusée, utilisateur sans permission refusé, entreprise bloquée refusée (ancienne session et URL connue), restauration conforme aux droits antérieurs. Tester aussi chemins encodés, lien direct au stockage et variantes d'hôtes, en FR/EN pour les réponses applicatives.

Aucune de ces corrections d'exploitation n'a été appliquée par cet audit. La revue de production et les tests d'accès doivent être documentés avant d'affirmer que le blocage couvre les fichiers privés.
