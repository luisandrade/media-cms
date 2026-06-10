import re
import secrets
import string
from dataclasses import dataclass
from urllib.parse import quote

import requests
from django.conf import settings
from requests.auth import HTTPDigestAuth


WOWZA_APP_NAME_INVALID_CHARS_RE = re.compile(r"[<>:'\"/\\|?*~]")
WOWZA_APP_NAME_INVALID_MESSAGE = 'El nombre no puede contener <, >, :, comillas, /, \\, |, ?, *, .. o ~.'


class WowzaAPIError(Exception):
    def __init__(self, message, *, status_code=None, data=None):
        super().__init__(message)
        self.status_code = status_code
        self.data = data


@dataclass
class WowzaClient:
    base_url: str = ""
    username: str = ""
    password: str = ""
    timeout: int = 5

    def __post_init__(self):
        self.base_url = (self.base_url or settings.WOWZA_ADMIN_API_BASE).rstrip("/")
        self.username = self.username or settings.WOWZA_ADMIN_USERNAME
        self.password = self.password or settings.WOWZA_ADMIN_PASSWORD
        self.timeout = self.timeout or settings.WOWZA_ADMIN_TIMEOUT_SECONDS

    def request(self, method, path, data=None):
        url = self.base_url + "/" + path.lstrip("/")
        try:
            response = requests.request(
                method,
                url,
                json=data,
                headers={
                    "Accept": "application/json; charset=utf-8",
                    "Content-Type": "application/json; charset=utf-8",
                },
                auth=HTTPDigestAuth(self.username, self.password),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise WowzaAPIError("No fue posible conectar con Wowza.", data={"detail": str(exc)}) from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {"body": response.text}

        if response.status_code >= 400:
            if isinstance(payload, dict):
                detail = payload.get("message") or payload.get("error") or payload.get("body") or response.reason
            else:
                detail = str(payload) or response.reason
            raise WowzaAPIError(detail, status_code=response.status_code, data=payload)

        return payload

    def status(self):
        return self.request("GET", "applications")

    def create_live_application(self, *, name, storage_user_id, schedule_id=None, publish_username=None, publish_password=None):
        schedule_id = schedule_id or name
        app_data = wowza_live_application_payload(name=name, storage_user_id=storage_user_id)
        try:
            created = self.request("POST", "applications", app_data)
        except WowzaAPIError as exc:
            if exc.status_code != 409:
                raise
            updated = self.update_live_application(name=name, storage_user_id=storage_user_id)
            created = {
                "success": True,
                "message": "La aplicación ya existía en Wowza y fue actualizada.",
                "data": exc.data,
                "updated": updated,
            }
        advanced = self.update_advanced_settings(name=name, schedule_id=schedule_id)
        publisher = self.create_publisher(
            app_name=name,
            publisher_name=publish_username or name,
            password=publish_password,
        )
        return {"success": True, "application": created, "advanced_settings": advanced, "publisher": publisher}

    def update_live_application(self, *, name, storage_user_id):
        return self.request(
            "PUT",
            f"applications/{quote_wowza_path_segment(name)}",
            wowza_live_application_payload(name=name, storage_user_id=storage_user_id),
        )

    def delete_live_application(self, *, name):
        deleted = self.request("DELETE", f"applications/{quote_wowza_path_segment(name)}")
        return {"success": True, "application": deleted}

    def create_publisher(self, *, app_name, publisher_name, password):
        payload = wowza_publisher_payload(publisher_name=publisher_name, password=password)
        try:
            return self.request("POST", f"applications/{quote_wowza_path_segment(app_name)}/publishers", payload)
        except WowzaAPIError as exc:
            if exc.status_code != 409:
                raise
            updated = self.update_publisher(app_name=app_name, publisher_name=publisher_name, password=password)
            return {"success": True, "message": "El publisher ya existía en Wowza y fue actualizado.", "data": updated}

    def update_publisher(self, *, app_name, publisher_name, password):
        return self.request(
            "PUT",
            f"applications/{quote_wowza_path_segment(app_name)}/publishers/{quote_wowza_path_segment(publisher_name)}",
            wowza_publisher_payload(publisher_name=publisher_name, password=password),
        )

    def delete_publisher(self, *, app_name, publisher_name):
        return self.request(
            "DELETE",
            f"applications/{quote_wowza_path_segment(app_name)}/publishers/{quote_wowza_path_segment(publisher_name)}",
        )

    def update_advanced_settings(self, *, name, schedule_id):
        return self.request("POST", f"applications/{quote_wowza_path_segment(name)}/adv", wowza_advanced_settings_payload(schedule_id))


def validate_wowza_app_name(value):
    value = (value or "").strip()
    if not value:
        raise ValueError("Ingresa un nombre para la aplicación.")
    if len(value) > 80:
        raise ValueError("El nombre no puede superar 80 caracteres.")
    if WOWZA_APP_NAME_INVALID_CHARS_RE.search(value) or ".." in value:
        raise ValueError(WOWZA_APP_NAME_INVALID_MESSAGE)
    return value


def quote_wowza_path_segment(value):
    return quote(str(value), safe="")


def generate_wowza_publish_password(length=10):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def wowza_publisher_payload(*, publisher_name, password):
    return {
        "publisherName": publisher_name,
        "password": password,
        "description": f"Publisher {publisher_name} creado desde MediaCMS",
    }


def wowza_live_application_payload(*, name, storage_user_id):
    security_config = {
        "publishRequirePassword": True,
        "publishAuthenticationMethod": settings.WOWZA_PUBLISH_AUTH_METHOD,
    }
    if settings.WOWZA_PUBLISH_PASSWORD_FILE:
        security_config["publishPasswordFile"] = settings.WOWZA_PUBLISH_PASSWORD_FILE

    return {
        "name": name,
        "appType": "Live",
        "clientStreamReadAccess": "*",
        "clientStreamWriteAccess": "*",
        "description": f"App {name} creada desde MediaCMS",
        "streamConfig": {
            "streamType": "live",
            "storageDir": f"{settings.WOWZA_APP_STORAGE_ROOT.rstrip('/')}/{storage_user_id}",
            "liveStreamPacketizer": ["cupertinostreamingpacketizer"],
        },
        "httpCORSHeadersEnabled": True,
        "httpStreamers": ["cupertinostreaming"],
        "securityConfig": security_config,
    }


def wowza_advanced_settings_payload(schedule_id):
    return {
        "modules": [
            {
                "order": 0,
                "name": "base",
                "description": "Base",
                "class": "com.wowza.wms.module.ModuleCore",
            },
            {
                "order": 1,
                "name": "logging",
                "description": "Client Logging",
                "class": "com.wowza.wms.module.ModuleClientLogging",
            },
            {
                "order": 2,
                "name": "flvplayback",
                "description": "FLVPlayback",
                "class": "com.wowza.wms.module.ModuleFLVPlayback",
            },
            {
                "order": 3,
                "name": "streamPublisher",
                "description": "Schedules streams and playlists.",
                "class": "com.wowza.wms.plugin.streampublisher.ModuleStreamPublisher",
            },
            {
                "order": 4,
                "name": "modulePushPublish",
                "description": "ModulePushPublish enable StreamTarget.",
                "class": "com.wowza.wms.pushpublish.module.ModulePushPublish",
            },
        ],
        "advancedSettings": [
            {
                "enabled": True,
                "canRemove": True,
                "name": "streamPublisherSmilFile",
                "value": f"streamschedule-{schedule_id}.smil",
                "type": "String",
                "section": "/Root/Application",
            },
            {
                "enabled": True,
                "canRemove": True,
                "name": "pushPublishDebug",
                "value": True,
                "type": "Boolean",
                "section": "/Root/Application",
            },
            {
                "enabled": True,
                "canRemove": True,
                "name": "bufferSeekIO",
                "value": True,
                "type": "Boolean",
                "section": "/Root/Application/MediaReader",
            },
            {
                "enabled": True,
                "canRemove": True,
                "name": "pushPublishMapPath",
                "value": "${com.wowza.wms.context.VHostConfigHome}/conf/${com.wowza.wms.context.Application}/PushPublishMap.txt",
                "type": "String",
                "section": "/Root/Application",
            },
        ],
    }
