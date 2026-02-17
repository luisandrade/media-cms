from __future__ import annotations

from django.conf import settings
from django.db import models


class DownloadEntitlement(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_REVOKED = "revoked"

    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_REVOKED, "Revoked"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    media = models.ForeignKey("files.Media", on_delete=models.CASCADE)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    paid_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "media")
        indexes = [
            models.Index(fields=["user", "media", "status"]),
        ]


class Payment(models.Model):
    PROVIDER_FLOW = "flow"

    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_PAID, "Paid"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELED, "Canceled"),
    )

    provider = models.CharField(max_length=20, default=PROVIDER_FLOW)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    media = models.ForeignKey("files.Media", on_delete=models.CASCADE)

    amount = models.PositiveIntegerField(help_text="Amount in minor units (e.g. CLP pesos).")
    currency = models.CharField(max_length=10, default="CLP")

    provider_token = models.CharField(max_length=120, blank=True, null=True)
    provider_order_id = models.CharField(max_length=120, blank=True, null=True)

    paid_at = models.DateTimeField(null=True, blank=True)

    raw_create_response = models.JSONField(blank=True, null=True)
    raw_confirm_payload = models.JSONField(blank=True, null=True)
    raw_status_response = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["provider", "provider_token"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["user", "media", "status"]),
        ]
