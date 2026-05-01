# Monitoring production JOATHAM Manager

Cette fiche sert au diagnostic de base de `https://app.joatham.com` sans afficher de secrets.

## Etat du service

Risque : un service en redemarrage boucle peut provoquer des erreurs intermittentes.

```bash
sudo systemctl status joatham --no-pager
sudo journalctl -u joatham -n 100 --no-pager -l
```

## Logs Nginx

Risque : une erreur Nginx peut masquer une application Django saine.

```bash
sudo tail -n 100 /var/log/nginx/error.log
sudo tail -n 100 /var/log/nginx/access.log
```

## Health checks

Risque : `/health/db/` indique seulement si la base repond. Il ne doit jamais exposer les identifiants PostgreSQL.

```bash
curl -I https://app.joatham.com/health/
curl -s https://app.joatham.com/health/
curl -I https://app.joatham.com/health/db/
curl -s https://app.joatham.com/health/db/
```

Si `HEALTH_CHECK_TOKEN` est defini en production, utiliser l'en-tete dedie :

```bash
curl -I -H "X-Health-Token: $HEALTH_CHECK_TOKEN" https://app.joatham.com/health/db/
curl -s -H "X-Health-Token: $HEALTH_CHECK_TOKEN" https://app.joatham.com/health/db/
```

Reponses attendues :

```json
{"status": "ok"}
```

## Test du formulaire public

Risque : cette commande cree une vraie question publique de test en production. Utiliser un email `.invalid`, puis archiver la demande dans l'espace super admin.

```bash
COOKIE_JAR="$(mktemp)"
CSRF_TOKEN="$(
  curl -s -c "$COOKIE_JAR" https://app.joatham.com/question-avant-inscription/ \
  | sed -n 's/.*name="csrfmiddlewaretoken" value="\([^"]*\)".*/\1/p' \
  | head -n 1
)"

curl -s -o /tmp/joatham_public_question_test.html -w "%{http_code} %{redirect_url}\n" \
  -b "$COOKIE_JAR" \
  -c "$COOKIE_JAR" \
  -H "Referer: https://app.joatham.com/question-avant-inscription/" \
  -X POST https://app.joatham.com/question-avant-inscription/ \
  --data-urlencode "csrfmiddlewaretoken=$CSRF_TOKEN" \
  --data-urlencode "nom=Monitoring Test" \
  --data-urlencode "email=monitoring-test@example.invalid" \
  --data-urlencode "telephone=+243000000000" \
  --data-urlencode "entreprise=Monitoring" \
  --data-urlencode "sujet=Test monitoring formulaire public" \
  --data-urlencode "message=Test de supervision du formulaire public JOATHAM Manager."
```

Resultat attendu : `302 https://app.joatham.com/question-avant-inscription/merci/`.

Verifier ensuite les logs applicatifs :

```bash
sudo journalctl -u joatham --since "5 minutes ago" --no-pager -l
sudo tail -n 100 /var/log/nginx/error.log
```

## Variables d'environnement monitoring

Ne jamais commiter de DSN reel. La configuration Sentry est activee uniquement si `SENTRY_DSN` existe.

```bash
SENTRY_DSN=
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0
DJANGO_LOG_LEVEL=INFO
DJANGO_REQUEST_LOG_LEVEL=ERROR
DJANGO_SECURITY_LOG_LEVEL=WARNING
HEALTH_CHECK_TOKEN=
```
