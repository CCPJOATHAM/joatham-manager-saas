from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("date_creation", "entreprise", "module", "action", "utilisateur", "objet_type", "objet_id")
    list_filter = ("module", "action", "entreprise")
    search_fields = ("description", "objet_type", "action")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
