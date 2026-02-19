from __future__ import annotations

from datetime import datetime
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from urllib.parse import urlsplit, urlunsplit
import logging
from django.db.models import Max, Q
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView

from files.models import Encoding, Media
from files.serializers import MediaSerializer

from .flow import FlowClient
from .emails import (
    send_download_purchase_confirmation_email,
    send_download_purchase_problem_email,
    send_payment_integration_error_to_admins,
)
from .models import DownloadEntitlement, Payment


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
        media.media_type == "video"
        and bool(getattr(settings, "VIDEO_DOWNLOAD_REQUIRES_PAYMENT", True))
        and bool(media.allow_download)
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

        if not media.allow_download:
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
            payment.raw_create_response = {"error": str(exc)}
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
            payment.raw_create_response = {"error": str(exc)}
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
                    "Compra realizada con éxito. Ya puedes descargar el video.",
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

        if not media.allow_download:
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
