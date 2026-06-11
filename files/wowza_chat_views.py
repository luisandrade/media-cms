from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .live_chat import (
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
                "can_write": user_can_write_live_chat(request.user),
                "can_moderate": user_can_moderate_live_chat(request.user),
            }
        )

    def post(self, request, app_name):
        app = get_object_or_404(WowzaApplication, name=app_name, is_active=True)
        if not user_can_write_live_chat(request.user):
            return Response({"detail": "Necesitas una suscripción activa para escribir en el chat."}, status=status.HTTP_403_FORBIDDEN)

        try:
            message = create_chat_message(stream=app, user=request.user, message=request.data.get("message"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payload = serialize_chat_message(message)
        broadcast_chat_event(app.id, {"type": "message.created", "message": payload})
        return Response(payload, status=status.HTTP_201_CREATED)


class WowzaLiveChatMessageDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def delete(self, request, app_name, message_id):
        app = get_object_or_404(WowzaApplication, name=app_name, is_active=True)
        if not user_can_moderate_live_chat(request.user):
            return Response({"detail": "No tienes permisos para moderar este chat."}, status=status.HTTP_403_FORBIDDEN)

        message = get_object_or_404(StreamChatMessage, id=message_id, stream=app)
        soft_delete_chat_message(message=message, deleted_by=request.user)
        broadcast_chat_event(app.id, {"type": "message.deleted", "id": message.id})
        return Response(status=status.HTTP_204_NO_CONTENT)
