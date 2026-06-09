from __future__ import annotations

from datetime import datetime
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from urllib.parse import urlsplit, urlunsplit
import logging
from django.db.models import Max, Q
from django.db import transaction
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView

from files.models import Encoding, Media
from files.serializers import MediaSerializer

from .flow import FlowAPIError, FlowClient
from .emails import (
    send_download_purchase_confirmation_email,
    send_download_purchase_problem_email,
    send_payment_integration_error_to_admins,
)
from .models import (
    DownloadEntitlement,
    FlowCustomer,
    Payment,
    SubscriptionPlan,
    UserSubscription,
    parse_flow_datetime,
    user_has_active_subscription,
)


logger = logging.getLogger(__name__)


def _flow_terminal_failure(status_value: Any) -> str | None:
    """Map Flow status to our terminal failure states.

    Common numeric mapping in Flow integrations:
    - 1: pending
    - 2: paid
    - 3: rejected/failed
    - 4: canceled
    """

    if status_value is None:
        return None

    try:
        numeric = int(status_value)
    except Exception:  # noqa: BLE001
        numeric = None

    if numeric == 3:
        return Payment.STATUS_FAILED
    if numeric == 4:
        return Payment.STATUS_CANCELED

    s = str(status_value).strip().lower()
    if s in ("rejected", "reject", "failed", "failure", "error"):
        return Payment.STATUS_FAILED
    if s in ("canceled", "cancelled", "canceled_by_user", "cancel"):
        return Payment.STATUS_CANCELED
    return None


def video_download_requires_payment(media: Media) -> bool:
    return (
        video_download_is_enabled(media)
        and bool(getattr(settings, "VIDEO_DOWNLOAD_REQUIRES_PAYMENT", True))
    )


def video_download_is_enabled(media: Media) -> bool:
    return (
        media.media_type == "video"
        and bool(media.allow_download)
        and bool(getattr(settings, "VIDEO_DOWNLOAD_ENABLED", True))
    )


def download_price_for_media(media: Media) -> int:
    return int(getattr(settings, "VIDEO_DOWNLOAD_PRICE_CLP", 990))


def video_stream_requires_payment(media: Media) -> bool:
    return (
        media.media_type == "video"
        and bool(getattr(media, "stream", ""))
        and bool(getattr(settings, "VIDEO_STREAM_REQUIRES_PAYMENT", True))
    )


def stream_price_for_media(media: Media) -> int:
    return int(getattr(settings, "VIDEO_STREAM_PRICE_CLP", getattr(settings, "VIDEO_DOWNLOAD_PRICE_CLP", 990)))


def _entitlement_is_active(entitlement: DownloadEntitlement) -> bool:
    if entitlement.status != DownloadEntitlement.STATUS_ACTIVE:
        return False
    if entitlement.expires_at and entitlement.expires_at <= timezone.now():
        return False
    return True


def user_has_entitlement(user, media: Media) -> bool:
    if not user or not user.is_authenticated:
        return False
    ent = DownloadEntitlement.objects.filter(user=user, media=media).first()
    return bool(ent and _entitlement_is_active(ent))


def grant_entitlement(*, user, media: Media, paid_at: datetime | None = None) -> DownloadEntitlement:
    ent, _created = DownloadEntitlement.objects.get_or_create(user=user, media=media)
    ent.status = DownloadEntitlement.STATUS_ACTIVE
    ent.paid_at = paid_at or timezone.now()
    ent.save(update_fields=["status", "paid_at", "updated_at"])
    return ent


def subscription_feature_enabled() -> bool:
    return bool(getattr(settings, "FLOW_SUBSCRIPTION_ENABLED", False))


def _flow_duplicate_customer_external_id(data: dict[str, Any] | None) -> bool:
    if not data:
        return False
    detail = str(data.get("message") or data.get("error") or data.get("detail") or "").lower()
    return "externalid" in detail and "customer" in detail


def _duplicate_customer_message() -> str:
    return (
        "La cuenta de suscripción ya existe para tu usuario. "
        "Si no ves tu suscripción activa, contáctanos para sincronizarla."
    )


def _subscription_status_from_flow(value: Any) -> str:
    try:
        numeric = int(value)
    except Exception:  # noqa: BLE001
        numeric = None

    if numeric == 1:
        return UserSubscription.STATUS_ACTIVE
    if numeric == 2:
        return UserSubscription.STATUS_TRIAL
    if numeric == 4:
        return UserSubscription.STATUS_CANCELED
    if numeric == 0:
        return UserSubscription.STATUS_INACTIVE
    return UserSubscription.STATUS_INACTIVE


def _subscription_plan_defaults() -> dict[str, Any]:
    return {
        "name": getattr(settings, "FLOW_SUBSCRIPTION_PLAN_NAME", "Suscripción mensual"),
        "currency": getattr(settings, "FLOW_SUBSCRIPTION_CURRENCY", "CLP"),
        "amount": int(getattr(settings, "FLOW_SUBSCRIPTION_PRICE_CLP", 0)),
        "interval": int(getattr(settings, "FLOW_SUBSCRIPTION_INTERVAL", SubscriptionPlan.INTERVAL_MONTHLY)),
        "interval_count": int(getattr(settings, "FLOW_SUBSCRIPTION_INTERVAL_COUNT", 1)),
        "trial_period_days": int(getattr(settings, "FLOW_SUBSCRIPTION_TRIAL_DAYS", 0)),
        "days_until_due": int(getattr(settings, "FLOW_SUBSCRIPTION_DAYS_UNTIL_DUE", 3)),
        "periods_number": int(getattr(settings, "FLOW_SUBSCRIPTION_PERIODS_NUMBER", 0)),
        "charges_retries_number": int(getattr(settings, "FLOW_SUBSCRIPTION_CHARGES_RETRIES", 3)),
        "currency_convert_option": int(getattr(settings, "FLOW_SUBSCRIPTION_CURRENCY_CONVERT_OPTION", 1)),
        "is_public": bool(getattr(settings, "FLOW_SUBSCRIPTION_PUBLIC", False)),
        "is_active": True,
    }


def get_default_subscription_plan() -> SubscriptionPlan:
    plan_id = getattr(settings, "FLOW_SUBSCRIPTION_PLAN_ID", "media-cms-monthly")
    defaults = _subscription_plan_defaults()
    plan, _created = SubscriptionPlan.objects.update_or_create(flow_plan_id=plan_id, defaults=defaults)
    return plan


def ensure_remote_subscription_plan(flow: FlowClient, plan: SubscriptionPlan, request) -> SubscriptionPlan:
    callback_url = getattr(settings, "FLOW_SUBSCRIPTION_PLAN_CALLBACK_URL", None)
    if callback_url:
        callback_url = _coerce_https_if_forwarded(request, callback_url)

    data = flow.get_plan(plan_id=plan.flow_plan_id)
    if data.get("planId"):
        plan.raw_flow_response = data
        plan.save(update_fields=["raw_flow_response", "updated_at"])
        return plan

    data = flow.create_plan(
        plan_id=plan.flow_plan_id,
        name=plan.name,
        amount=plan.amount,
        currency=plan.currency,
        interval=plan.interval,
        interval_count=plan.interval_count,
        trial_period_days=plan.trial_period_days,
        days_until_due=plan.days_until_due,
        periods_number=plan.periods_number,
        url_callback=callback_url,
        charges_retries_number=plan.charges_retries_number,
        currency_convert_option=plan.currency_convert_option,
    )
    plan.raw_flow_response = data
    plan.save(update_fields=["raw_flow_response", "updated_at"])
    return plan


def _user_display_name(user) -> str:
    full_name = (getattr(user, "name", "") or getattr(user, "get_full_name", lambda: "")()).strip()
    if full_name:
        return full_name
    return getattr(user, "username", str(user.pk))


def _flow_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def sync_flow_customer(customer: FlowCustomer, data: dict[str, Any]) -> FlowCustomer:
    customer.status = _flow_text(data.get("status"), customer.status or "")
    customer.pay_mode = _flow_text(data.get("pay_mode"), customer.pay_mode or "")
    customer.credit_card_type = _flow_text(data.get("creditCardType"), customer.credit_card_type or "")
    customer.last4_card_digits = _flow_text(data.get("last4CardDigits"), customer.last4_card_digits or "")
    customer.card_number = _flow_text(data.get("cardNumber"), customer.card_number or "")
    customer.issuer_bank = _flow_text(data.get("issuerBank"), customer.issuer_bank or "")
    customer.register_date = parse_flow_datetime(data.get("registerDate")) or customer.register_date
    customer.raw_last_register_status = data
    customer.save(
        update_fields=[
            "status",
            "pay_mode",
            "credit_card_type",
            "last4_card_digits",
            "card_number",
            "issuer_bank",
            "register_date",
            "raw_last_register_status",
            "updated_at",
        ]
    )
    return customer


def sync_user_subscription(subscription: UserSubscription, data: dict[str, Any], *, raw_status: dict[str, Any] | None = None) -> UserSubscription:
    flow_status = data.get("status")
    try:
        subscription.flow_status = int(flow_status) if flow_status is not None else subscription.flow_status
    except Exception:  # noqa: BLE001
        pass
    subscription.flow_subscription_id = data.get("subscriptionId", subscription.flow_subscription_id)
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
    subscription.raw_subscription_response = data
    if raw_status is not None:
        subscription.raw_subscription_status = raw_status
    subscription.save(
        update_fields=[
            "flow_subscription_id",
            "status",
            "flow_status",
            "subscription_start",
            "subscription_end",
            "period_start",
            "period_end",
            "next_invoice_date",
            "trial_start",
            "trial_end",
            "cancel_at_period_end",
            "cancel_at",
            "last_synced_at",
            "raw_subscription_response",
            "raw_subscription_status",
            "updated_at",
        ]
    )
    return subscription


def serialize_subscription(subscription: UserSubscription | None) -> dict[str, Any]:
    if not subscription:
        return {"status": "none", "active": False}
    return {
        "status": subscription.status,
        "active": subscription.is_active,
        "plan": {
            "id": subscription.plan.flow_plan_id,
            "name": subscription.plan.name,
            "amount": subscription.plan.amount,
            "currency": subscription.plan.currency,
            "interval": subscription.plan.interval,
            "interval_count": subscription.plan.interval_count,
            "trial_period_days": subscription.plan.trial_period_days,
        },
        "customer_id": subscription.customer.flow_customer_id,
        "subscription_id": subscription.flow_subscription_id,
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "next_invoice_date": subscription.next_invoice_date,
        "period_end": subscription.period_end,
        "last4_card_digits": subscription.customer.last4_card_digits,
        "credit_card_type": subscription.customer.credit_card_type,
    }


def _download_filename(*, title: str, suffix: str) -> str:
    safe = slugify(title) or "media"
    return f"{safe}{suffix}"


def _coerce_https_if_forwarded(request, url: str) -> str:
    proto = (request.META.get("HTTP_X_FORWARDED_PROTO") or "").split(",")[0].strip().lower()
    if proto == "https" and url.startswith("http://"):
        parts = urlsplit(url)
        return urlunsplit(("https", parts.netloc, parts.path, parts.query, parts.fragment))
    return url


class VideoDownloadCheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, friendly_token: str):
        media = get_object_or_404(Media, friendly_token=friendly_token)

        if not video_download_is_enabled(media):
            return Response({"detail": "Download disabled."}, status=status.HTTP_403_FORBIDDEN)

        if media.media_type != "video":
            return Response({"detail": "Payment required only for videos."}, status=status.HTTP_400_BAD_REQUEST)

        if not video_download_requires_payment(media):
            return Response({"detail": "Payment not required."}, status=status.HTTP_400_BAD_REQUEST)

        if user_has_entitlement(request.user, media):
            return HttpResponseRedirect(media.get_absolute_url())

        amount = download_price_for_media(media)
        payment = Payment.objects.create(
            user=request.user,
            media=media,
            amount=amount,
            currency=getattr(settings, "VIDEO_DOWNLOAD_CURRENCY", "CLP"),
            status=Payment.STATUS_PENDING,
        )

        flow = FlowClient()

        if not flow.is_configured():
            if bool(getattr(settings, "FLOW_FAKE_SUCCESS", False)):
                payment.status = Payment.STATUS_PAID
                payment.paid_at = timezone.now()
                payment.save(update_fields=["status", "paid_at", "updated_at"])
                grant_entitlement(user=request.user, media=media, paid_at=payment.paid_at)
                return HttpResponseRedirect(media.get_absolute_url())
            return Response(
                {"detail": "Flow is not configured. Set FLOW_API_KEY and FLOW_SECRET_KEY."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        url_return = getattr(settings, "FLOW_URL_RETURN", None) or request.build_absolute_uri(reverse("flow_return"))
        url_confirmation = (
            getattr(settings, "FLOW_URL_CONFIRMATION", None)
            or request.build_absolute_uri(reverse("flow_confirm"))
        )
        url_return = _coerce_https_if_forwarded(request, url_return)
        url_confirmation = _coerce_https_if_forwarded(request, url_confirmation)

        subject = f"Download video: {media.title}"[:45]
        email = getattr(request.user, "email", "") or ""

        optional: dict[str, Any] = {
            "optional": f"payment_id={payment.id}&media={media.friendly_token}",
        }

        try:
            result = flow.create_payment(
                commerce_order=str(payment.id),
                subject=subject,
                amount=amount,
                email=email,
                url_return=url_return,
                url_confirmation=url_confirmation,
                optional=optional,
            )
        except Exception as exc:  # noqa: BLE001
            payment.status = Payment.STATUS_FAILED
            payment.raw_create_response = exc.raw if isinstance(exc, FlowAPIError) else {"error": str(exc)}
            payment.save(update_fields=["status", "raw_create_response", "updated_at"])
            return Response(
                {"detail": "Failed to create Flow payment.", "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        payment.provider_token = result.token
        payment.raw_create_response = result.raw
        payment.save(update_fields=["provider_token", "raw_create_response", "updated_at"])

        return HttpResponseRedirect(result.redirect_url)


class VideoStreamCheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, friendly_token: str):
        media = get_object_or_404(Media, friendly_token=friendly_token)

        if media.media_type != "video" or not getattr(media, "stream", ""):
            return Response({"detail": "Stream payment is available only for stream videos."}, status=status.HTTP_400_BAD_REQUEST)

        if not video_stream_requires_payment(media):
            return Response({"detail": "Payment not required."}, status=status.HTTP_400_BAD_REQUEST)

        if user_has_entitlement(request.user, media):
            return HttpResponseRedirect(media.get_absolute_url())

        amount = stream_price_for_media(media)
        payment = Payment.objects.create(
            user=request.user,
            media=media,
            amount=amount,
            currency=getattr(settings, "VIDEO_STREAM_CURRENCY", getattr(settings, "VIDEO_DOWNLOAD_CURRENCY", "CLP")),
            status=Payment.STATUS_PENDING,
        )

        flow = FlowClient()

        if not flow.is_configured():
            if bool(getattr(settings, "FLOW_FAKE_SUCCESS", False)):
                payment.status = Payment.STATUS_PAID
                payment.paid_at = timezone.now()
                payment.save(update_fields=["status", "paid_at", "updated_at"])
                grant_entitlement(user=request.user, media=media, paid_at=payment.paid_at)
                return HttpResponseRedirect(media.get_absolute_url())
            return Response(
                {"detail": "Flow is not configured. Set FLOW_API_KEY and FLOW_SECRET_KEY."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        url_return = getattr(settings, "FLOW_URL_RETURN", None) or request.build_absolute_uri(reverse("flow_return"))
        url_confirmation = (
            getattr(settings, "FLOW_URL_CONFIRMATION", None) or request.build_absolute_uri(reverse("flow_confirm"))
        )
        url_return = _coerce_https_if_forwarded(request, url_return)
        url_confirmation = _coerce_https_if_forwarded(request, url_confirmation)

        subject = f"Stream access: {media.title}"[:45]
        email = getattr(request.user, "email", "") or ""

        optional: dict[str, Any] = {
            "optional": f"payment_id={payment.id}&media={media.friendly_token}&purpose=stream",
        }

        try:
            result = flow.create_payment(
                commerce_order=str(payment.id),
                subject=subject,
                amount=amount,
                email=email,
                url_return=url_return,
                url_confirmation=url_confirmation,
                optional=optional,
            )
        except Exception as exc:  # noqa: BLE001
            payment.status = Payment.STATUS_FAILED
            payment.raw_create_response = exc.raw if isinstance(exc, FlowAPIError) else {"error": str(exc)}
            payment.save(update_fields=["status", "raw_create_response", "updated_at"])
            return Response(
                {"detail": "Failed to create Flow payment.", "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        payment.provider_token = result.token
        payment.raw_create_response = result.raw
        payment.save(update_fields=["provider_token", "raw_create_response", "updated_at"])

        return HttpResponseRedirect(result.redirect_url)


class FlowReturnView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    parser_classes = [FormParser, JSONParser]

    @csrf_exempt
    def dispatch(self, *args, **kwargs):  # type: ignore[override]
        return super().dispatch(*args, **kwargs)

    def _redirect_target(self, request):
        # Flow returns the user back here. Some setups use GET, others POST.
        # The definitive payment status is processed via the server-to-server confirm endpoint.
        def _first(value: Any) -> str | None:
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                return str(value[0]) if value else None
            return str(value)

        def _payload() -> dict[str, Any]:
            out: dict[str, Any] = {}
            try:
                if hasattr(request, "data") and hasattr(request.data, "keys"):
                    for k in request.data.keys():
                        out[str(k)] = _first(request.data.get(k))
            except Exception:  # noqa: BLE001
                pass
            try:
                for k in request.POST.keys():
                    if str(k) not in out:
                        out[str(k)] = _first(request.POST.get(k))
            except Exception:  # noqa: BLE001
                pass
            return out

        payload = _payload()

        friendly_token = (
            _first(request.GET.get("media"))
            or _first(request.GET.get("m"))
            or _first(payload.get("media"))
            or _first(payload.get("m"))
        )

        token = _first(payload.get("token")) or _first(request.GET.get("token"))
        commerce_order = _first(payload.get("commerceOrder")) or _first(payload.get("commerce_order"))

        payment: Payment | None = None
        if commerce_order:
            try:
                payment = Payment.objects.filter(id=int(str(commerce_order))).select_related("media").first()
            except Exception:  # noqa: BLE001
                payment = None
        if not payment and token:
            payment = Payment.objects.filter(provider_token=str(token)).select_related("media").first()

        # Best-effort: confirm status here too so user sees immediate feedback.
        # The authoritative flow is still the server-to-server confirm webhook.
        if payment and payment.status != Payment.STATUS_PAID:
            flow = FlowClient()
            if flow.is_configured() and payment.provider_token:
                try:
                    status_data = flow.get_status(token=payment.provider_token)
                    payment.raw_status_response = status_data
                    payment.save(update_fields=["raw_status_response", "updated_at"])

                    if isinstance(status_data, dict) and status_data.get("error"):
                        send_payment_integration_error_to_admins(payment=payment, error=str(status_data.get("error")))

                    paid = False
                    flow_status = status_data.get("status")
                    if flow_status in ("paid", "PAID", Payment.STATUS_PAID, 2, "2", "success", "SUCCESS"):
                        paid = True
                    if not paid:
                        payment_status = None
                        if isinstance(status_data.get("paymentData"), dict):
                            payment_status = status_data["paymentData"].get("status")
                        if payment_status in ("paid", "PAID", 2, "2", "success", "SUCCESS"):
                            paid = True
                    if not paid:
                        try:
                            numeric_status = int(flow_status) if flow_status is not None else None
                        except Exception:  # noqa: BLE001
                            numeric_status = None
                        if numeric_status == 2:
                            paid = True

                    terminal = _flow_terminal_failure(flow_status)
                    if not terminal and isinstance(status_data.get("paymentData"), dict):
                        terminal = _flow_terminal_failure(status_data["paymentData"].get("status"))

                    if terminal and payment.status != terminal and payment.status != Payment.STATUS_PAID:
                        payment.status = terminal
                        payment.save(update_fields=["status", "updated_at"])
                        send_download_purchase_problem_email(
                            payment=payment,
                            problem=("Pago rechazado." if terminal == Payment.STATUS_FAILED else "Pago cancelado."),
                        )

                    if paid and payment.status != Payment.STATUS_PAID:
                        payment.status = Payment.STATUS_PAID
                        payment.paid_at = timezone.now()
                        payment.save(update_fields=["status", "paid_at", "updated_at"])
                        grant_entitlement(user=payment.user, media=payment.media, paid_at=payment.paid_at)
                        send_download_purchase_confirmation_email(payment=payment)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Flow return: getStatus failed. payment_id=%s err=%s", payment.id, exc)
                    send_payment_integration_error_to_admins(payment=payment, error=str(exc))

        # UI feedback
        if payment:
            if payment.status == Payment.STATUS_PAID:
                messages.add_message(
                    request,
                    messages.INFO,
                    "Compra realizada con éxito. Ya puedes descargar el video, haz clic en el botón DESCARGAR para elegir una de las calidades disponibles.",
                )
            elif payment.status == Payment.STATUS_FAILED:
                messages.add_message(
                    request,
                    messages.ERROR,
                    "Hubo un problema procesando tu pago. Si el cobro se realizó, contáctanos para validarlo.",
                )
            else:
                messages.add_message(
                    request,
                    messages.WARNING,
                    "Pago recibido. Estamos confirmándolo; si no se habilita en unos segundos, recarga la página.",
                )

        if friendly_token:
            try:
                media = Media.objects.filter(friendly_token=str(friendly_token)).first()
                if media:
                    return media.get_absolute_url()
            except Exception:  # noqa: BLE001
                pass

        if payment and payment.media:
            return payment.media.get_absolute_url()

        return "/"

    def get(self, request):
        return HttpResponseRedirect(self._redirect_target(request))

    def post(self, request):
        return HttpResponseRedirect(self._redirect_target(request))


class FlowConfirmView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    parser_classes = [FormParser, JSONParser]

    @csrf_exempt
    def dispatch(self, *args, **kwargs):  # type: ignore[override]
        return super().dispatch(*args, **kwargs)

    def get(self, request):
        # Flow confirmation should be POST; accept GET only to aid debugging.
        return HttpResponse("Method not allowed", status=405, content_type="text/plain")

    def post(self, request):
        def _first(value: Any) -> str | None:
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                return str(value[0]) if value else None
            return str(value)

        def _normalized_payload() -> dict[str, Any]:
            # DRF FormParser may yield QueryDict where dict(...) becomes lists.
            out: dict[str, Any] = {}
            try:
                if hasattr(request, "data") and hasattr(request.data, "keys"):
                    for k in request.data.keys():
                        out[str(k)] = _first(request.data.get(k))
            except Exception:  # noqa: BLE001
                pass
            try:
                for k in request.POST.keys():
                    if str(k) not in out:
                        out[str(k)] = _first(request.POST.get(k))
            except Exception:  # noqa: BLE001
                pass
            return out

        payload = _normalized_payload()

        token = _first(request.POST.get("token")) or _first(getattr(request, "data", {}).get("token")) or _first(
            request.GET.get("token")
        )
        commerce_order = (
            _first(request.POST.get("commerceOrder"))
            or _first(request.POST.get("commerce_order"))
            or _first(getattr(request, "data", {}).get("commerceOrder"))
            or _first(getattr(request, "data", {}).get("commerce_order"))
        )

        # Flow expects a fast 200 + "OK" body. The real status is persisted in our DB.
        if not token and not commerce_order:
            logger.error("Flow confirm missing token/commerceOrder. payload=%s", payload)
            return HttpResponse("OK", status=200, content_type="text/plain")

        payment: Payment | None = None
        if commerce_order:
            try:
                payment = Payment.objects.filter(id=int(str(commerce_order))).first()
            except Exception:  # noqa: BLE001
                payment = None

        if not payment and token:
            payment = Payment.objects.filter(provider_token=str(token)).first()

        flow = FlowClient()

        # If we still can't find a Payment but we do have the Flow token, ask Flow for status
        # to recover commerceOrder and map it back to our Payment id.
        status_data: dict[str, Any] | None = None
        if not payment and token and flow.is_configured():
            try:
                status_data = flow.get_status(token=str(token))
                recovered_order = _first(status_data.get("commerceOrder")) or _first(status_data.get("commerce_order"))
                if recovered_order:
                    payment = Payment.objects.filter(id=int(str(recovered_order))).first()
                    commerce_order = commerce_order or recovered_order
            except Exception as exc:  # noqa: BLE001
                logger.error("Flow confirm: could not recover payment via getStatus. token=%s err=%s", token, exc)

        if not payment:
            logger.error("Flow confirm: Payment not found. token=%s commerce_order=%s payload=%s", token, commerce_order, payload)
            return HttpResponse("OK", status=200, content_type="text/plain")

        payment.raw_confirm_payload = payload
        if token and not payment.provider_token:
            payment.provider_token = str(token)
        payment.save(update_fields=["raw_confirm_payload", "provider_token", "updated_at"])

        if not flow.is_configured() or not payment.provider_token:
            logger.error("Flow confirm: Flow not configured or missing provider_token. payment_id=%s", payment.id)
            return HttpResponse("OK", status=200, content_type="text/plain")

        if status_data is None:
            try:
                status_data = flow.get_status(token=payment.provider_token)
            except Exception as exc:  # noqa: BLE001
                payment.raw_status_response = {"error": str(exc)}
                payment.save(update_fields=["raw_status_response", "updated_at"])
                logger.error("Flow confirm: getStatus failed. payment_id=%s err=%s", payment.id, exc)
                send_payment_integration_error_to_admins(payment=payment, error=str(exc))
                return HttpResponse("OK", status=200, content_type="text/plain")

        payment.raw_status_response = status_data
        payment.save(update_fields=["raw_status_response", "updated_at"])

        if isinstance(status_data, dict) and status_data.get("error"):
            send_payment_integration_error_to_admins(payment=payment, error=str(status_data.get("error")))

        paid = False
        flow_status = status_data.get("status")
        if flow_status in ("paid", "PAID", Payment.STATUS_PAID, 2, "2", "success", "SUCCESS"):
            paid = True

        # Some responses embed payment status:
        if not paid:
            payment_status = None
            if isinstance(status_data.get("paymentData"), dict):
                payment_status = status_data["paymentData"].get("status")
            if payment_status in ("paid", "PAID", 2, "2", "success", "SUCCESS"):
                paid = True

        # Fallbacks seen in some Flow payloads
        if not paid:
            numeric_status = None
            try:
                numeric_status = int(flow_status) if flow_status is not None else None
            except Exception:  # noqa: BLE001
                numeric_status = None
            if numeric_status == 2:
                paid = True

        terminal = _flow_terminal_failure(flow_status)
        if not terminal and isinstance(status_data.get("paymentData"), dict):
            terminal = _flow_terminal_failure(status_data["paymentData"].get("status"))

        if terminal and payment.status != terminal and payment.status != Payment.STATUS_PAID:
            payment.status = terminal
            payment.save(update_fields=["status", "updated_at"])
            send_download_purchase_problem_email(
                payment=payment,
                problem=("Pago rechazado." if terminal == Payment.STATUS_FAILED else "Pago cancelado."),
            )

        if paid and payment.status != Payment.STATUS_PAID:
            payment.status = Payment.STATUS_PAID
            payment.paid_at = timezone.now()
            payment.save(update_fields=["status", "paid_at", "updated_at"])
            grant_entitlement(user=payment.user, media=payment.media, paid_at=payment.paid_at)
            send_download_purchase_confirmation_email(payment=payment)

        return HttpResponse("OK", status=200, content_type="text/plain")


class SubscriptionPortalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not subscription_feature_enabled():
            return HttpResponse("Not found", status=404)

        plan = get_default_subscription_plan()
        subscription = UserSubscription.objects.filter(user=request.user).select_related("plan", "customer").first()
        context = {
            "plan": plan,
            "subscription": subscription,
            "subscription_data": serialize_subscription(subscription),
            "flow_subscription_enabled": True,
        }
        return render(request, "payments/subscription_portal.html", context)


class SubscriptionStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not subscription_feature_enabled():
            return Response({"detail": "Subscriptions disabled."}, status=status.HTTP_404_NOT_FOUND)

        plan = get_default_subscription_plan()
        subscription = UserSubscription.objects.filter(user=request.user).select_related("plan", "customer").first()
        return Response(
            {
                "enabled": True,
                "plan": {
                    "id": plan.flow_plan_id,
                    "name": plan.name,
                    "amount": plan.amount,
                    "currency": plan.currency,
                    "interval": plan.interval,
                    "interval_count": plan.interval_count,
                    "trial_period_days": plan.trial_period_days,
                },
                "subscription": serialize_subscription(subscription),
            }
        )


class SubscriptionActivateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [FormParser, MultiPartParser, JSONParser]

    def post(self, request):
        if not subscription_feature_enabled():
            return Response({"detail": "Subscriptions disabled."}, status=status.HTTP_404_NOT_FOUND)

        if user_has_active_subscription(request.user):
            messages.info(request, "Tu suscripción ya está activa.")
            return HttpResponseRedirect(reverse("subscription_portal"))

        flow = FlowClient()
        if not flow.is_configured():
            return Response(
                {"detail": "Flow is not configured. Set FLOW_API_KEY and FLOW_SECRET_KEY."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        email = (getattr(request.user, "email", "") or "").strip()
        if not email:
            messages.error(request, "Tu cuenta no tiene un email válido para registrar la suscripción.")
            return HttpResponseRedirect(reverse("subscription_portal"))

        plan = get_default_subscription_plan()
        try:
            ensure_remote_subscription_plan(flow, plan, request)
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
            if isinstance(exc, FlowAPIError) and exc.raw:
                detail = str(exc.raw.get("message") or exc.raw.get("error") or detail)
            messages.error(request, f"No fue posible preparar el plan en Flow: {detail}")
            return HttpResponseRedirect(reverse("subscription_portal"))

        with transaction.atomic():
            customer = FlowCustomer.objects.filter(user=request.user).first()
            customer_created = False
            if not customer:
                try:
                    customer_data = flow.create_customer(
                        name=_user_display_name(request.user),
                        email=email,
                        external_id=f"user-{request.user.pk}",
                    )
                except Exception as exc:  # noqa: BLE001
                    if isinstance(exc, FlowAPIError) and _flow_duplicate_customer_external_id(exc.raw):
                        messages.warning(request, _duplicate_customer_message())
                    else:
                        messages.error(
                            request,
                            "No fue posible crear el cliente en Flow. Inténtalo nuevamente en unos minutos.",
                        )
                    return HttpResponseRedirect(reverse("subscription_portal"))
                if not customer_data.get("customerId"):
                    if _flow_duplicate_customer_external_id(customer_data):
                        messages.warning(request, _duplicate_customer_message())
                        return HttpResponseRedirect(reverse("subscription_portal"))
                    detail = customer_data.get("message") or customer_data.get("error") or "Flow no devolvió customerId."
                    messages.error(request, f"No fue posible crear el cliente en Flow: {detail}")
                    return HttpResponseRedirect(reverse("subscription_portal"))
                customer = FlowCustomer.objects.create(
                    user=request.user,
                    flow_customer_id=_flow_text(customer_data.get("customerId")),
                    external_id=_flow_text(customer_data.get("externalId"), f"user-{request.user.pk}"),
                    email=_flow_text(customer_data.get("email"), email),
                    name=_flow_text(customer_data.get("name"), _user_display_name(request.user)),
                    pay_mode=_flow_text(customer_data.get("pay_mode")),
                    status=_flow_text(customer_data.get("status")),
                    credit_card_type=_flow_text(customer_data.get("creditCardType")),
                    last4_card_digits=_flow_text(customer_data.get("last4CardDigits")),
                    card_number=_flow_text(customer_data.get("cardNumber")),
                    issuer_bank=_flow_text(customer_data.get("issuerBank")),
                    raw_create_response=customer_data,
                )
                customer_created = True

            if not customer_created:
                messages.warning(request, _duplicate_customer_message())
                return HttpResponseRedirect(reverse("subscription_portal"))

            subscription, _created = UserSubscription.objects.update_or_create(
                user=request.user,
                defaults={
                    "plan": plan,
                    "customer": customer,
                    "status": UserSubscription.STATUS_PENDING_CARD,
                    "raw_subscription_response": None,
                },
            )

            callback_url = getattr(settings, "FLOW_SUBSCRIPTION_REGISTER_RETURN_URL", None) or request.build_absolute_uri(
                reverse("subscription_register_return")
            )
            callback_url = _coerce_https_if_forwarded(request, callback_url)
            try:
                register_result = flow.register_customer(customer_id=customer.flow_customer_id, url_return=callback_url)
            except Exception as exc:  # noqa: BLE001
                detail = str(exc)
                if isinstance(exc, FlowAPIError) and exc.raw:
                    detail = str(exc.raw.get("message") or exc.raw.get("error") or detail)
                messages.error(request, f"No fue posible iniciar el registro de tarjeta en Flow: {detail}")
                return HttpResponseRedirect(reverse("subscription_portal"))

            subscription.register_token = register_result.token or ""
            subscription.raw_register_response = register_result.raw
            subscription.status = UserSubscription.STATUS_PENDING_CARD
            subscription.save(update_fields=["register_token", "raw_register_response", "status", "updated_at"])

        return HttpResponseRedirect(register_result.redirect_url)


class SubscriptionRegisterReturnView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    parser_classes = [FormParser, MultiPartParser, JSONParser]

    @csrf_exempt
    def dispatch(self, *args, **kwargs):  # type: ignore[override]
        return super().dispatch(*args, **kwargs)

    def _handle(self, request):
        if not subscription_feature_enabled():
            return HttpResponseRedirect("/")

        token = request.POST.get("token") or request.GET.get("token") or getattr(request, "data", {}).get("token")
        if not token:
            messages.error(request, "Flow no devolvió el token de registro de la tarjeta.")
            return HttpResponseRedirect(reverse("subscription_portal"))

        subscription = UserSubscription.objects.filter(register_token=str(token)).select_related("customer", "plan", "user").first()
        if not subscription:
            logger.error("Subscription register return without local subscription. token=%s", token)
            return HttpResponseRedirect(reverse("subscription_portal"))

        flow = FlowClient()
        try:
            register_status = flow.get_customer_register_status(token=str(token))
        except Exception as exc:  # noqa: BLE001
            subscription.status = UserSubscription.STATUS_REGISTRATION_FAILED
            subscription.raw_register_response = {"error": str(exc)}
            subscription.save(update_fields=["status", "raw_register_response", "updated_at"])
            messages.error(request, f"No fue posible confirmar el registro de la tarjeta: {exc}")
            return HttpResponseRedirect(reverse("subscription_portal"))

        sync_flow_customer(subscription.customer, register_status)
        subscription.raw_register_response = register_status

        if str(register_status.get("status")) != "1":
            subscription.status = UserSubscription.STATUS_REGISTRATION_FAILED
            subscription.save(update_fields=["status", "raw_register_response", "updated_at"])
            messages.error(request, "Flow no pudo registrar la tarjeta para la suscripción.")
            return HttpResponseRedirect(reverse("subscription_portal"))

        subscription_data = flow.create_subscription(
            plan_id=subscription.plan.flow_plan_id,
            customer_id=subscription.customer.flow_customer_id,
            trial_period_days=subscription.plan.trial_period_days if subscription.plan.trial_period_days else None,
            periods_number=subscription.plan.periods_number if subscription.plan.periods_number else None,
        )

        sync_user_subscription(subscription, subscription_data)
        subscription.register_token = ""
        subscription.save(update_fields=["register_token", "updated_at"])
        messages.info(request, "Tu suscripción quedó activada correctamente.")
        return HttpResponseRedirect(reverse("subscription_portal"))

    def get(self, request):
        return self._handle(request)

    def post(self, request):
        return self._handle(request)


class SubscriptionCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [FormParser, MultiPartParser, JSONParser]

    def post(self, request):
        if not subscription_feature_enabled():
            return Response({"detail": "Subscriptions disabled."}, status=status.HTTP_404_NOT_FOUND)

        subscription = UserSubscription.objects.filter(user=request.user).select_related("plan", "customer").first()
        if not subscription or not subscription.flow_subscription_id:
            return Response({"detail": "No active subscription."}, status=status.HTTP_400_BAD_REQUEST)

        flow = FlowClient()
        at_period_end = str(request.data.get("at_period_end", request.POST.get("at_period_end", "1"))) != "0"
        response_data = flow.cancel_subscription(
            subscription_id=subscription.flow_subscription_id,
            at_period_end=at_period_end,
        )
        sync_user_subscription(subscription, response_data)
        messages.info(request, "Tu solicitud de cancelación fue enviada a Flow.")
        return HttpResponseRedirect(reverse("subscription_portal"))


class PurchasedMediaListView(ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MediaSerializer

    def get_queryset(self):
        now = timezone.now()
        return (
            Media.objects.filter(
                downloadentitlement__user=self.request.user,
                downloadentitlement__status=DownloadEntitlement.STATUS_ACTIVE,
            )
            .filter(Q(downloadentitlement__expires_at__isnull=True) | Q(downloadentitlement__expires_at__gt=now))
            .annotate(purchased_at=Max("downloadentitlement__paid_at"))
            .order_by("-purchased_at")
            .distinct()
        )


class VideoDownloadFileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, friendly_token: str):
        media = get_object_or_404(Media, friendly_token=friendly_token)

        if not video_download_is_enabled(media):
            return Response({"detail": "Download disabled."}, status=status.HTTP_403_FORBIDDEN)

        if media.media_type != "video":
            return Response({"detail": "Not a video."}, status=status.HTTP_400_BAD_REQUEST)

        if video_download_requires_payment(media) and not user_has_entitlement(request.user, media):
            return Response({"detail": "Payment required."}, status=status.HTTP_402_PAYMENT_REQUIRED)

        encoding_id = request.GET.get("encoding_id")
        kind = request.GET.get("kind")

        file_path: str | None = None
        filename: str = _download_filename(title=media.title, suffix=".mp4")

        if encoding_id:
            encoding = get_object_or_404(Encoding, id=encoding_id, media=media)
            if encoding.status != "success" or encoding.progress != 100:
                return Response({"detail": "Encoding not ready."}, status=status.HTTP_400_BAD_REQUEST)
            file_path = encoding.media_file.path if encoding.media_file else None
            ext = (encoding.profile.extension or "mp4") if encoding.profile else "mp4"
            filename = _download_filename(title=media.title, suffix=f".{ext}")
        elif kind == "original":
            file_path = media.media_file.path if media.media_file else None
            filename = _download_filename(title=media.title, suffix="")
        else:
            return Response({"detail": "Missing encoding_id or kind=original."}, status=status.HTTP_400_BAD_REQUEST)

        if not file_path:
            return Response({"detail": "File not available."}, status=status.HTTP_404_NOT_FOUND)

        x_accel_prefix = getattr(settings, "PAYMENTS_X_ACCEL_REDIRECT_PREFIX", None)
        if x_accel_prefix:
            # Expect nginx to map PAYMENTS_X_ACCEL_REDIRECT_PREFIX to MEDIA_ROOT.
            # Example: /protected-media/ -> /path/to/media_files/
            rel = None
            media_root = getattr(settings, "MEDIA_ROOT", "")
            if media_root and file_path.startswith(media_root):
                rel = file_path[len(media_root) :]
            if rel is not None:
                resp = HttpResponse()
                resp["X-Accel-Redirect"] = x_accel_prefix.rstrip("/") + "/" + rel.lstrip("/")
                resp["Content-Disposition"] = f'attachment; filename="{filename}"'
                return resp

        try:
            response = FileResponse(open(file_path, "rb"), as_attachment=True, filename=filename)
        except FileNotFoundError:
            return Response({"detail": "File not found."}, status=status.HTTP_404_NOT_FOUND)

        return response
