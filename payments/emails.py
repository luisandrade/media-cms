from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage

from .models import Payment


def send_download_purchase_confirmation_email(*, payment: Payment) -> bool:
    user = getattr(payment, "user", None)
    media = getattr(payment, "media", None)

    to_email = getattr(user, "email", "") or ""
    if not to_email:
        return False

    portal_name = getattr(settings, "PORTAL_NAME", "MediaVMS")

    media_url = ""
    try:
        ssl_frontend_host = getattr(settings, "SSL_FRONTEND_HOST", "") or ""
        if media and ssl_frontend_host:
            media_url = ssl_frontend_host.rstrip("/") + media.get_absolute_url()
    except Exception:  # noqa: BLE001
        media_url = ""

    title = f"[{portal_name}] - Compra confirmada"

    amount = getattr(payment, "amount", None)
    currency = getattr(payment, "currency", "") or ""

    msg_lines: list[str] = [
        "Tu compra fue confirmada exitosamente.",
        "",
    ]

    if media:
        msg_lines.append(f"Contenido: {media.title}")
    if amount is not None:
        msg_lines.append(f"Monto: {amount} {currency}".strip())
    if media_url:
        msg_lines.extend(["", f"Puedes volver al video aquí: {media_url}"])

    msg_lines.append("")
    msg_lines.append("Gracias por tu compra.")

    email = EmailMessage(title, "\n".join(msg_lines), settings.DEFAULT_FROM_EMAIL, [to_email])
    email.send(fail_silently=True)
    return True


def send_download_purchase_problem_email(*, payment: Payment, problem: str) -> bool:
    user = getattr(payment, "user", None)
    media = getattr(payment, "media", None)

    to_email = getattr(user, "email", "") or ""
    if not to_email:
        return False

    portal_name = getattr(settings, "PORTAL_NAME", "MediaVMS")
    title = f"[{portal_name}] - Problema con tu compra"

    media_url = ""
    try:
        ssl_frontend_host = getattr(settings, "SSL_FRONTEND_HOST", "") or ""
        if media and ssl_frontend_host:
            media_url = ssl_frontend_host.rstrip("/") + media.get_absolute_url()
    except Exception:  # noqa: BLE001
        media_url = ""

    msg_lines: list[str] = [
        "Detectamos un problema al procesar tu compra.",
        "",
        f"Detalle: {problem}",
    ]

    if media:
        msg_lines.extend(["", f"Contenido: {media.title}"])
    if media_url:
        msg_lines.extend(["", f"Link: {media_url}"])

    msg_lines.extend(
        [
            "",
            "Si el cobro se realizó pero no se habilitó la descarga, responde este correo o contáctanos para validarlo.",
        ]
    )

    email = EmailMessage(title, "\n".join(msg_lines), settings.DEFAULT_FROM_EMAIL, [to_email])
    email.send(fail_silently=True)
    return True


def send_payment_integration_error_to_admins(*, payment: Payment, error: str) -> bool:
    admin_list = list(getattr(settings, "ADMIN_EMAIL_LIST", []) or [])
    if not admin_list:
        return False

    portal_name = getattr(settings, "PORTAL_NAME", "MediaVMS")
    title = f"[{portal_name}] - Error integración Flow (payment_id={payment.id})"

    msg = "\n".join(
        [
            "Hubo un error consultando el estado del pago en Flow.",
            "",
            f"payment_id: {payment.id}",
            f"status local: {payment.status}",
            f"provider_token: {payment.provider_token}",
            "",
            f"error: {error}",
        ]
    )

    email = EmailMessage(title, msg, settings.DEFAULT_FROM_EMAIL, admin_list)
    email.send(fail_silently=True)
    return True
