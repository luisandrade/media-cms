from django.contrib import admin

from .models import DownloadEntitlement, FlowCustomer, Payment, SubscriptionPlan, UserSubscription


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


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("flow_plan_id", "name", "amount", "currency", "interval", "is_active", "updated_at")
    list_filter = ("is_active", "currency", "interval")
    search_fields = ("flow_plan_id", "name")
    readonly_fields = ("raw_flow_response", "created_at", "updated_at")


@admin.register(FlowCustomer)
class FlowCustomerAdmin(admin.ModelAdmin):
    list_display = ("user", "flow_customer_id", "email", "status", "credit_card_type", "last4_card_digits", "updated_at")
    list_filter = ("status", "credit_card_type", "updated_at")
    search_fields = ("user__username", "user__email", "flow_customer_id", "external_id")
    raw_id_fields = ("user",)
    readonly_fields = (
        "raw_create_response",
        "raw_last_register_status",
        "created_at",
        "updated_at",
    )


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "plan",
        "status",
        "flow_subscription_id",
        "cancel_at_period_end",
        "next_invoice_date",
        "updated_at",
    )
    list_filter = ("status", "cancel_at_period_end", "updated_at")
    search_fields = ("user__username", "user__email", "flow_subscription_id", "customer__flow_customer_id")
    raw_id_fields = ("user", "plan", "customer")
    readonly_fields = (
        "raw_register_response",
        "raw_subscription_response",
        "raw_subscription_status",
        "created_at",
        "updated_at",
    )
