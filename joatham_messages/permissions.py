from joatham_users.permissions import require_permission


def can_view_messages(user):
    require_permission(user, "messages.view")


def can_create_suggestion(user):
    require_permission(user, "suggestions.create")
