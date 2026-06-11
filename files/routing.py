from django.urls import re_path

from . import consumers


websocket_urlpatterns = [
    re_path(r"^ws/live-chat/(?P<stream_id>\d+)/$", consumers.WowzaLiveChatConsumer.as_asgi()),
]
