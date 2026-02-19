from django.contrib import admin

from .models import DownloadEntitlement, Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider",
        "status",
        "user",
        "media",
        "amount",
        "currency",
        "provider_token",
        "paid_at",
        "created_at",
    )
    list_filter = ("provider", "status", "currency", "created_at", "paid_at")
    search_fields = (
        "id",
        "provider_token",
        "provider_order_id",
        "user__username",
        "user__email",
        "media__friendly_token",
        "media__title",
    )
    ordering = ("-created_at",)
    raw_id_fields = ("user", "media")

    readonly_fields = (
        "provider",
        "status",
        "user",
        "media",
        "amount",
        "currency",
        "provider_token",
        "provider_order_id",
        "paid_at",
        "raw_create_response",
        "raw_confirm_payload",
        "raw_status_response",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Pago",
            {
                "fields": (
                    "provider",
                    "status",
                    "user",
                    "media",
                    "amount",
                    "currency",
                    "paid_at",
                )
            },
        ),
        (
            "Flow",
            {
                "fields": (
                    "provider_token",
                    "provider_order_id",
                )
            },
        ),
        (
            "Payloads",
            {
                "fields": (
                    "raw_create_response",
                    "raw_confirm_payload",
                    "raw_status_response",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


@admin.register(DownloadEntitlement)
class DownloadEntitlementAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "user",
        "media",
        "paid_at",
        "expires_at",
        "created_at",
    )
    list_filter = ("status", "created_at", "paid_at", "expires_at")
    search_fields = (
        "user__username",
        "user__email",
        "media__friendly_token",
        "media__title",
    )
    ordering = ("-created_at",)
    raw_id_fields = ("user", "media")

    readonly_fields = (
        "created_at",
        "updated_at",
    )
