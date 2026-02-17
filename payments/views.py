from __future__ import annotations

from datetime import datetime
from typing import Any

from django.conf import settings
from django.http import FileResponse, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from files.models import Encoding, Media

from .flow import FlowClient
from .models import DownloadEntitlement, Payment


def video_download_requires_payment(media: Media) -> bool:
    return (
        media.media_type == "video"
        and bool(getattr(settings, "VIDEO_DOWNLOAD_REQUIRES_PAYMENT", True))
        and bool(media.allow_download)
    )


def download_price_for_media(media: Media) -> int:
    return int(getattr(settings, "VIDEO_DOWNLOAD_PRICE_CLP", 990))


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

        url_return = request.build_absolute_uri("/payments/flow/return/")
        url_confirmation = request.build_absolute_uri("/payments/flow/confirm/")

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


class FlowReturnView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        # Flow redirects the user back here. The definitive payment status
        # is processed via the server-to-server confirm endpoint.
        # We simply redirect user to home or back to media if we can infer it.
        friendly_token = request.GET.get("media") or request.GET.get("m")
        if friendly_token:
            try:
                media = Media.objects.filter(friendly_token=friendly_token).first()
                if media:
                    return HttpResponseRedirect(media.get_absolute_url())
            except Exception:  # noqa: BLE001
                pass
        return HttpResponseRedirect("/")


class FlowConfirmView(APIView):
    permission_classes = [permissions.AllowAny]
    parser_classes = [FormParser, JSONParser]

    @csrf_exempt
    def dispatch(self, *args, **kwargs):  # type: ignore[override]
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        payload: dict[str, Any]
        if isinstance(request.data, dict):
            payload = dict(request.data)
        else:
            payload = {}

        token = payload.get("token") or request.POST.get("token") or request.GET.get("token")
        commerce_order = payload.get("commerceOrder") or payload.get("commerce_order")

        payment: Payment | None = None
        if commerce_order:
            try:
                payment = Payment.objects.filter(id=int(str(commerce_order))).first()
            except Exception:  # noqa: BLE001
                payment = None

        if not payment and token:
            payment = Payment.objects.filter(provider_token=str(token)).first()

        if not payment:
            return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)

        payment.raw_confirm_payload = payload
        if token and not payment.provider_token:
            payment.provider_token = str(token)
        payment.save(update_fields=["raw_confirm_payload", "provider_token", "updated_at"])

        flow = FlowClient()
        if not flow.is_configured() or not payment.provider_token:
            return Response({"detail": "Flow not configured."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            status_data = flow.get_status(token=payment.provider_token)
        except Exception as exc:  # noqa: BLE001
            payment.raw_status_response = {"error": str(exc)}
            payment.save(update_fields=["raw_status_response", "updated_at"])
            return Response({"detail": "Failed to check status."}, status=status.HTTP_502_BAD_GATEWAY)

        payment.raw_status_response = status_data
        payment.save(update_fields=["raw_status_response", "updated_at"])

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

        if paid and payment.status != Payment.STATUS_PAID:
            payment.status = Payment.STATUS_PAID
            payment.paid_at = timezone.now()
            payment.save(update_fields=["status", "paid_at", "updated_at"])
            grant_entitlement(user=payment.user, media=payment.media, paid_at=payment.paid_at)

        return Response({"ok": True}, status=status.HTTP_200_OK)


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
