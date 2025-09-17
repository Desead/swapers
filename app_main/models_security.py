from django.db import models
from django.conf import settings

class BlocklistEntry(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="+"
    )
    email = models.EmailField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Запись чёрного списка"
        verbose_name_plural = "Чёрный список"
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["ip_address"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return  f"name: {self.user.email}"
