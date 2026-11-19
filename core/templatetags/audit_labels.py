from django import template
from core.audit_i18n import action_label, module_label

register = template.Library()
register.filter("audit_action", action_label)
register.filter("audit_module", module_label)
