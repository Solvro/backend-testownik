from django.db import models

# Create your models here.
class MaintenanceMode(models.Model):
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return "Maintenance mode is: ON" if self.is_active else "Maintenance mode is: OFF"

    class Meta:
        verbose_name = "Maintenance mode"
        verbose_name_plural = "Maintenance modes"