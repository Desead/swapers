from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _t


class ExchangeAvailabilityLog(models.Model):
    exchange = models.ForeignKey(
        "app_market.Exchange",
        on_delete=models.CASCADE,
        related_name="availability_logs",
        db_index=True,
        verbose_name=_t("Поставщик"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_t("Время проверки"),
    )
    available = models.BooleanField(verbose_name=_t("Доступен"))
    code = models.CharField(max_length=32, verbose_name=_t("Код результата"))
    detail = models.CharField(
        max_length=512, blank=True, default="", verbose_name=_t("Детали")
    )
    latency_ms = models.PositiveIntegerField(
        default=0, verbose_name=_t("Задержка, мс")
    )

    class Meta:
        verbose_name = _t("История доступности")
        verbose_name_plural = _t("История доступности")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["exchange", "-created_at"]),
        ]

    def __str__(self) -> str:
        state = "OK" if self.available else "DOWN"
        return f"{self.exchange} · {self.created_at:%Y-%m-%d %H:%M:%S} · {self.code} · {state}"
