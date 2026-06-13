from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


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
        app_label = "payments"


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
        app_label = "payments"


class SubscriptionPlan(models.Model):
    INTERVAL_DAILY = 1
    INTERVAL_WEEKLY = 2
    INTERVAL_MONTHLY = 3
    INTERVAL_YEARLY = 4

    INTERVAL_CHOICES = (
        (INTERVAL_DAILY, "Daily"),
        (INTERVAL_WEEKLY, "Weekly"),
        (INTERVAL_MONTHLY, "Monthly"),
        (INTERVAL_YEARLY, "Yearly"),
    )

    flow_plan_id = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=150)
    currency = models.CharField(max_length=10, default="CLP")
    amount = models.PositiveIntegerField()
    interval = models.PositiveSmallIntegerField(choices=INTERVAL_CHOICES, default=INTERVAL_MONTHLY)
    interval_count = models.PositiveSmallIntegerField(default=1)
    trial_period_days = models.PositiveIntegerField(default=0)
    days_until_due = models.PositiveIntegerField(default=3)
    periods_number = models.PositiveIntegerField(default=0)
    charges_retries_number = models.PositiveIntegerField(default=3)
    currency_convert_option = models.PositiveSmallIntegerField(default=1)
    is_public = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    raw_flow_response = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["flow_plan_id", "is_active"])]
        app_label = "payments"

    def __str__(self):
        return f"{self.name} ({self.flow_plan_id})"


class FlowCustomer(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="flow_customer")
    flow_customer_id = models.CharField(max_length=120, unique=True)
    external_id = models.CharField(max_length=120, db_index=True)
    email = models.EmailField()
    name = models.CharField(max_length=255)
    pay_mode = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=20, blank=True)
    credit_card_type = models.CharField(max_length=40, blank=True)
    last4_card_digits = models.CharField(max_length=8, blank=True)
    card_number = models.CharField(max_length=32, blank=True)
    issuer_bank = models.CharField(max_length=120, blank=True)
    register_date = models.DateTimeField(null=True, blank=True)
    raw_create_response = models.JSONField(blank=True, null=True)
    raw_last_register_status = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["flow_customer_id", "status"])]
        app_label = "payments"

    def __str__(self):
        return f"{self.user.username} ({self.flow_customer_id})"


class UserSubscription(models.Model):
    FLOW_STATUS_INACTIVE = 0
    FLOW_STATUS_ACTIVE = 1
    FLOW_STATUS_TRIAL = 2
    FLOW_STATUS_CANCELED = 4

    STATUS_PENDING_CARD = "pending_card"
    STATUS_ACTIVE = "active"
    STATUS_TRIAL = "trial"
    STATUS_CANCELED = "canceled"
    STATUS_INACTIVE = "inactive"
    STATUS_REGISTRATION_FAILED = "registration_failed"

    STATUS_CHOICES = (
        (STATUS_PENDING_CARD, "Registro de tarjeta pendiente"),
        (STATUS_ACTIVE, "Activa"),
        (STATUS_TRIAL, "En período de trial"),
        (STATUS_CANCELED, "Cancelada"),
        (STATUS_INACTIVE, "Inactiva"),
        (STATUS_REGISTRATION_FAILED, "Registro fallido"),
    )

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions")
    customer = models.ForeignKey(FlowCustomer, on_delete=models.PROTECT, related_name="subscriptions")
    flow_subscription_id = models.CharField(max_length=120, unique=True, null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING_CARD)
    flow_status = models.IntegerField(null=True, blank=True)
    register_token = models.CharField(max_length=120, blank=True)
    subscription_start = models.DateTimeField(null=True, blank=True)
    subscription_end = models.DateTimeField(null=True, blank=True)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    next_invoice_date = models.DateTimeField(null=True, blank=True)
    morose = models.IntegerField(null=True, blank=True)
    trial_start = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancel_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    raw_register_response = models.JSONField(blank=True, null=True)
    raw_subscription_response = models.JSONField(blank=True, null=True)
    raw_subscription_status = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "updated_at"]),
            models.Index(fields=["flow_subscription_id"]),
        ]
        app_label = "payments"

    def __str__(self):
        return f"{self.user.username} - {self.status}"

    @property
    def is_active(self) -> bool:
        return (
            bool(self.flow_subscription_id)
            and self.flow_status in {self.FLOW_STATUS_ACTIVE, self.FLOW_STATUS_TRIAL}
            and (self.morose is None or self.morose == 0)
            and self.status in {self.STATUS_ACTIVE, self.STATUS_TRIAL}
        )


def _subscription_status_from_flow(value):
    try:
        numeric = int(value)
    except Exception:  # noqa: BLE001
        numeric = None

    if numeric == UserSubscription.FLOW_STATUS_ACTIVE:
        return UserSubscription.STATUS_ACTIVE
    if numeric == UserSubscription.FLOW_STATUS_TRIAL:
        return UserSubscription.STATUS_TRIAL
    if numeric == UserSubscription.FLOW_STATUS_CANCELED:
        return UserSubscription.STATUS_CANCELED
    if numeric == UserSubscription.FLOW_STATUS_INACTIVE:
        return UserSubscription.STATUS_INACTIVE
    return UserSubscription.STATUS_INACTIVE


def _subscription_access_sync_due(subscription: UserSubscription) -> bool:
    interval = int(getattr(settings, "FLOW_SUBSCRIPTION_ACCESS_SYNC_SECONDS", 3600))
    if interval < 0:
        return False
    if not subscription.last_synced_at:
        return True
    return subscription.last_synced_at <= timezone.now() - timezone.timedelta(seconds=interval)


def _sync_subscription_access_status(subscription: UserSubscription) -> UserSubscription:
    if not subscription.flow_subscription_id or not _subscription_access_sync_due(subscription):
        return subscription

    try:
        from .flow import FlowClient

        data = FlowClient().get_subscription(subscription_id=subscription.flow_subscription_id)
    except Exception:  # noqa: BLE001
        return subscription

    flow_status = data.get("status")
    try:
        subscription.flow_status = int(flow_status) if flow_status is not None else subscription.flow_status
    except Exception:  # noqa: BLE001
        pass
    try:
        subscription.morose = int(data.get("morose")) if data.get("morose") is not None else subscription.morose
    except Exception:  # noqa: BLE001
        pass

    subscription.status = _subscription_status_from_flow(flow_status)
    subscription.subscription_start = parse_flow_datetime(data.get("subscription_start"))
    subscription.subscription_end = parse_flow_datetime(data.get("subscription_end"))
    subscription.period_start = parse_flow_datetime(data.get("period_start"))
    subscription.period_end = parse_flow_datetime(data.get("period_end"))
    subscription.next_invoice_date = parse_flow_datetime(data.get("next_invoice_date"))
    subscription.trial_start = parse_flow_datetime(data.get("trial_start"))
    subscription.trial_end = parse_flow_datetime(data.get("trial_end"))
    subscription.cancel_at_period_end = bool(int(data.get("cancel_at_period_end", 0) or 0))
    subscription.cancel_at = parse_flow_datetime(data.get("cancel_at"))
    subscription.last_synced_at = timezone.now()
    subscription.raw_subscription_status = data
    subscription.raw_subscription_response = data
    subscription.save(
        update_fields=[
            "status",
            "flow_status",
            "subscription_start",
            "subscription_end",
            "period_start",
            "period_end",
            "next_invoice_date",
            "morose",
            "trial_start",
            "trial_end",
            "cancel_at_period_end",
            "cancel_at",
            "last_synced_at",
            "raw_subscription_status",
            "raw_subscription_response",
            "updated_at",
        ]
    )
    return subscription


def user_has_active_subscription(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    try:
        subscription = getattr(user, "subscription", None)
    except Exception:
        subscription = None
    if subscription:
        subscription = _sync_subscription_access_status(subscription)
    return bool(subscription and subscription.is_active)


def parse_flow_datetime(value):
    if not value:
        return None
    if isinstance(value, timezone.datetime):
        dt = value
    else:
        normalized = str(value).strip().replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = timezone.datetime.strptime(normalized, fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt
