from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .live_chat import (
    ban_user_from_live_chat,
    broadcast_chat_event,
    create_chat_message,
    list_chat_messages,
    serialize_chat_message,
    soft_delete_chat_message,
    user_can_access_live_chat,
    user_can_moderate_live_chat,
    user_can_write_live_chat,
)
from .models import StreamChatMessage, WowzaApplication


class WowzaLiveChatMessagesView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, app_name):
        app = get_object_or_404(WowzaApplication, name=app_name, is_active=True)
        if not user_can_access_live_chat(request.user):
            return Response({"detail": "Necesitas una suscripción activa para ver este chat."}, status=status.HTTP_403_FORBIDDEN)

        before_id = request.query_params.get("before_id")
        messages = list_chat_messages(app, before_id=before_id)
        return Response(
            {
                "results": [serialize_chat_message(message) for message in messages],
                "can_write": user_can_write_live_chat(request.user, app),
                "can_moderate": user_can_moderate_live_chat(request.user),
            }
        )

    def post(self, request, app_name):
        app = get_object_or_404(WowzaApplication, name=app_name, is_active=True)
        if not user_can_write_live_chat(request.user, app):
            return Response({"detail": "No puedes escribir en este chat."}, status=status.HTTP_403_FORBIDDEN)

        try:
            message = create_chat_message(stream=app, user=request.user, message=request.data.get("message"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        payload = serialize_chat_message(message)
        broadcast_chat_event(app.id, {"type": "message.created", "message": payload})
        return Response(payload, status=status.HTTP_201_CREATED)


class WowzaLiveChatMessageDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, app_name, message_id):
        app = get_object_or_404(WowzaApplication, name=app_name, is_active=True)
        if not user_can_moderate_live_chat(request.user):
            return Response({"detail": "No tienes permisos para moderar este chat."}, status=status.HTTP_403_FORBIDDEN)

        action = (request.data.get("action") or "").strip().lower()
        if action != "ban":
            return Response({"detail": "Acción no soportada."}, status=status.HTTP_400_BAD_REQUEST)

        message = get_object_or_404(StreamChatMessage.objects.select_related("user"), id=message_id, stream=app)
        if user_can_moderate_live_chat(message.user):
            return Response({"detail": "No puedes banear a otro moderador."}, status=status.HTTP_400_BAD_REQUEST)

        ban_user_from_live_chat(
            stream=app,
            user=message.user,
            banned_by=request.user,
            reason=request.data.get("reason") or "Moderación del chat",
        )
        soft_delete_chat_message(message=message, deleted_by=request.user)
        broadcast_chat_event(app.id, {"type": "message.deleted", "id": message.id})
        broadcast_chat_event(app.id, {"type": "user.banned", "user_id": message.user_id})
        return Response({"detail": "Usuario baneado del chat.", "user_id": message.user_id})

    def delete(self, request, app_name, message_id):
        app = get_object_or_404(WowzaApplication, name=app_name, is_active=True)
        if not user_can_moderate_live_chat(request.user):
            return Response({"detail": "No tienes permisos para moderar este chat."}, status=status.HTTP_403_FORBIDDEN)

        message = get_object_or_404(StreamChatMessage, id=message_id, stream=app)
        soft_delete_chat_message(message=message, deleted_by=request.user)
        broadcast_chat_event(app.id, {"type": "message.deleted", "id": message.id})
        return Response(status=status.HTTP_204_NO_CONTENT)
