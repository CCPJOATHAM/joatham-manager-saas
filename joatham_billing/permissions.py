from joatham_users.permissions import require_permission


def can_manage_factures(user):
    require_permission(user, "billing.manage")


def can_record_payment(user):
    require_permission(user, "billing.payments")


def can_view_factures(user):
    require_permission(user, "billing.view")
