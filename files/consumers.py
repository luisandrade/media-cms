from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.shortcuts import get_object_or_404

from .live_chat import (
    chat_group_name,
    create_chat_message,
    serialize_chat_message,
    soft_delete_chat_message,
    user_can_access_live_chat,
    user_can_moderate_live_chat,
    user_can_write_live_chat,
)
from .models import StreamChatMessage, WowzaApplication


class WowzaLiveChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.stream_id = int(self.scope["url_route"]["kwargs"]["stream_id"])
        self.user = self.scope.get("user")
        self.permissions = await self.get_permissions()
        if not self.permissions["can_access"]:
            await self.close(code=4403)
            return

        self.group_name = chat_group_name(self.stream_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {
                "type": "chat.ready",
                "can_write": self.permissions["can_write"],
                "can_moderate": self.permissions["can_moderate"],
            }
        )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        action = content.get("type")
        if action in {"chat.message", "message.create"}:
            await self.create_message(content.get("message"))
            return

        if action in {"message.delete", "chat.delete"}:
            await self.delete_message(content.get("id"))
            return

        await self.send_json({"type": "chat.error", "detail": "Acción no soportada."})

    async def create_message(self, message_text):
        if not self.permissions["can_write"]:
            await self.send_json({"type": "chat.error", "detail": "No tienes permisos para escribir en este chat."})
            return

        result = await self.create_message_in_db(message_text)
        if "error" in result:
            await self.send_json({"type": "chat.error", "detail": result["error"]})
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat.event",
                "event": {
                    "type": "message.created",
                    "message": result["message"],
                },
            },
        )

    async def delete_message(self, message_id):
        if not self.permissions["can_moderate"]:
            await self.send_json({"type": "chat.error", "detail": "No tienes permisos para moderar este chat."})
            return

        result = await self.delete_message_in_db(message_id)
        if "error" in result:
            await self.send_json({"type": "chat.error", "detail": result["error"]})
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat.event",
                "event": {
                    "type": "message.deleted",
                    "id": result["id"],
                },
            },
        )

    async def chat_event(self, event):
        await self.send_json(event["event"])

    @database_sync_to_async
    def get_permissions(self):
        stream = WowzaApplication.objects.filter(id=self.stream_id, is_active=True).first()
        can_access = bool(stream) and user_can_access_live_chat(self.user)
        return {
            "can_access": can_access,
            "can_write": can_access and user_can_write_live_chat(self.user, stream),
            "can_moderate": user_can_moderate_live_chat(self.user),
        }

    @database_sync_to_async
    def create_message_in_db(self, message_text):
        stream = get_object_or_404(WowzaApplication, id=self.stream_id, is_active=True)
        try:
            message = create_chat_message(stream=stream, user=self.user, message=message_text)
        except ValueError as exc:
            return {"error": str(exc)}
        except PermissionError as exc:
            return {"error": str(exc)}
        return {"message": serialize_chat_message(message)}

    @database_sync_to_async
    def delete_message_in_db(self, message_id):
        stream = get_object_or_404(WowzaApplication, id=self.stream_id, is_active=True)
        try:
            message = StreamChatMessage.objects.get(id=message_id, stream=stream)
        except StreamChatMessage.DoesNotExist:
            return {"error": "El mensaje no existe."}
        soft_delete_chat_message(message=message, deleted_by=self.user)
        return {"id": message.id}
