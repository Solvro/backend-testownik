from django.contrib import admin

from maintenance.models import MaintenanceMode


# Register your models here.
class MaintenanceModeAdmin(admin.ModelAdmin):
    list_display = ['is_active']

    def has_add_permission(self, request):
        return False if MaintenanceMode.objects.exists() else True

admin.site.register(MaintenanceMode, MaintenanceModeAdmin)