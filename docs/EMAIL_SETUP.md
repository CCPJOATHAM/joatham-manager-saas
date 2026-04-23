# Configuration email JOATHAM Manager

## Local

En local, le projet utilise par defaut :

```env
DJANGO_EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

Cela signifie que les emails ne partent pas vers un vrai serveur SMTP.
Le contenu complet du mail s'affiche dans le terminal qui execute :

```powershell
env\Scripts\python.exe manage.py runserver
```

## Production

Exemple de variables d'environnement :

```env
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_EMAIL_HOST=smtp.office365.com
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_HOST_USER=no-reply@tondomaine.com
DJANGO_EMAIL_HOST_PASSWORD=mot_de_passe_ou_app_password
DJANGO_EMAIL_USE_TLS=True
DJANGO_EMAIL_USE_SSL=False
DJANGO_EMAIL_TIMEOUT=30
DJANGO_DEFAULT_FROM_EMAIL=JOATHAM Manager <no-reply@tondomaine.com>
DJANGO_PASSWORD_RESET_TIMEOUT=3600
```

## Verification locale du mot de passe oublie

1. Ouvrir `/password-reset/`
2. Saisir un email existant
3. Valider le formulaire
4. Revenir au terminal du serveur Django
5. Copier le lien `http://127.0.0.1:8000/reset/...`
6. Ouvrir ce lien dans le navigateur
7. Saisir le nouveau mot de passe
8. Revenir sur `/login/` et tester la connexion
