from django.contrib import admin

from maintenance.models import MaintenanceMode


# Register your models here.
class MaintenanceModeAdmin(admin.ModelAdmin):
    list_display = ['is_active']

admin.site.register(MaintenanceMode, MaintenanceModeAdmin)