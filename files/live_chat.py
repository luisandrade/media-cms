import logging

from django.conf import settings
from django.utils import timezone

from .methods import is_mediacms_editor
from .models import StreamChatBan, StreamChatMessage


logger = logging.getLogger(__name__)
STREAM_CHAT_MAX_LENGTH = int(getattr(settings, "WOWZA_LIVE_CHAT_MAX_LENGTH", 500))
STREAM_CHAT_HISTORY_LIMIT = int(getattr(settings, "WOWZA_LIVE_CHAT_HISTORY_LIMIT", 50))


def user_can_access_live_chat(user):
    if not getattr(settings, "WOWZA_LIVE_CHAT_ENABLED", True):
        return False

    if not user or not getattr(user, "is_authenticated", False):
        return False

    if is_mediacms_editor(user):
        return True

    try:
        from payments.models import user_has_active_subscription

        return user_has_active_subscription(user)
    except Exception:
        return False


def user_is_banned_from_live_chat(user, stream):
    if not user or not getattr(user, "is_authenticated", False) or not stream:
        return False

    return StreamChatBan.objects.filter(stream=stream, user=user, is_active=True).exists()


def user_can_write_live_chat(user, stream=None):
    if not user_can_access_live_chat(user):
        return False
    if stream and user_is_banned_from_live_chat(user, stream):
        return False
    return True


def user_can_moderate_live_chat(user):
    return bool(user and getattr(user, "is_authenticated", False) and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)))


def normalize_chat_message(value):
    message = " ".join(str(value or "").split())
    if not message:
        raise ValueError("Ingresa un mensaje.")
    if len(message) > STREAM_CHAT_MAX_LENGTH:
        raise ValueError(f"El mensaje no puede superar {STREAM_CHAT_MAX_LENGTH} caracteres.")
    return message


def serialize_chat_message(message):
    user = message.user
    return {
        "id": message.id,
        "message": "" if message.is_deleted else message.message,
        "is_deleted": message.is_deleted,
        "is_pinned": message.is_pinned,
        "created_at": message.created_at.isoformat(),
        "user": {
            "id": user.id,
            "username": getattr(user, "username", "") or getattr(user, "email", "") or "Usuario",
        },
    }


def serialize_chat_ban(ban):
    user = ban.user
    banned_by = ban.banned_by
    return {
        "id": ban.id,
        "reason": ban.reason,
        "created_at": ban.created_at.isoformat(),
        "user": {
            "id": user.id,
            "username": getattr(user, "username", "") or getattr(user, "email", "") or "Usuario",
            "email": getattr(user, "email", "") or "",
        },
        "banned_by": {
            "id": banned_by.id,
            "username": getattr(banned_by, "username", "") or getattr(banned_by, "email", "") or "Moderador",
        }
        if banned_by
        else None,
    }


def ban_user_from_live_chat(*, stream, user, banned_by, reason=""):
    ban, _created = StreamChatBan.objects.update_or_create(
        stream=stream,
        user=user,
        is_active=True,
        defaults={
            "banned_by": banned_by,
            "reason": (reason or "").strip()[:255],
        },
    )
    return ban


def unban_user_from_live_chat(*, ban, unbanned_by):
    ban.is_active = False
    ban.save(update_fields=["is_active"])
    return ban


def chat_group_name(stream_id):
    return f"wowza_live_chat_{stream_id}"


def list_chat_messages(stream, *, before_id=None, limit=None):
    limit = min(int(limit or STREAM_CHAT_HISTORY_LIMIT), 100)
    queryset = StreamChatMessage.objects.select_related("user").filter(stream=stream, is_deleted=False).order_by("-created_at", "-id")
    if before_id:
        queryset = queryset.filter(id__lt=before_id)
    return list(reversed(list(queryset[:limit])))


def create_chat_message(*, stream, user, message):
    if user_is_banned_from_live_chat(user, stream):
        raise PermissionError("Has sido bloqueado para escribir en este chat.")
    return StreamChatMessage.objects.create(stream=stream, user=user, message=normalize_chat_message(message))


def soft_delete_chat_message(*, message, deleted_by):
    message.is_deleted = True
    message.deleted_by = deleted_by
    message.deleted_at = timezone.now()
    message.save(update_fields=["is_deleted", "deleted_by", "deleted_at"])
    return message


def broadcast_chat_event(stream_id, event):
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except ImportError:
        return

    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    try:
        async_to_sync(channel_layer.group_send)(
            chat_group_name(stream_id),
            {
                "type": "chat.event",
                "event": event,
            },
        )
    except Exception:
        logger.exception("No fue posible emitir evento del chat live stream_id=%s", stream_id)
