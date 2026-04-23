from django.contrib.auth import get_user_model


User = get_user_model()


def get_users_by_entreprise(entreprise):
    return User.objects.filter(entreprise=entreprise).order_by("role", "first_name", "last_name", "username")


def get_user_by_entreprise(entreprise, user_id):
    return get_users_by_entreprise(entreprise).get(id=user_id)
