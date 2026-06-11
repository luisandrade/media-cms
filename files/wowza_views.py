from django.conf import settings
from django.core.paginator import EmptyPage, Paginator
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import WowzaApplication
from .permissions import IsMediacmsAdmin
from .wowza import WowzaAPIError, WowzaClient, generate_wowza_publish_password, validate_wowza_app_name, wowza_has_incoming_streams


class WowzaStatusView(APIView):
    permission_classes = (IsMediacmsAdmin,)
    parser_classes = (JSONParser,)

    def get(self, request, format=None):
        try:
            payload = WowzaClient().status()
        except WowzaAPIError as exc:
            return Response(
                {
                    "success": False,
                    "message": str(exc),
                    "data": exc.data,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"success": True, "data": payload})


class WowzaApplicationCreateView(APIView):
    permission_classes = (IsMediacmsAdmin,)
    parser_classes = (JSONParser,)

    def get(self, request, format=None):
        page = parse_positive_int(request.GET.get("page"), default=1)
        page_size = min(parse_positive_int(request.GET.get("page_size"), default=10), 50)
        applications = WowzaApplication.objects.select_related("created_by").order_by("-add_date", "name")
        paginator = Paginator(applications, page_size)

        try:
            page_obj = paginator.page(page)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages or 1)

        live_statuses = live_statuses_for_applications(page_obj.object_list)

        return Response(
            {
                "success": True,
                "count": paginator.count,
                "page": page_obj.number,
                "page_size": page_size,
                "total_pages": paginator.num_pages,
                "results": [serialize_wowza_application(app, is_live=live_statuses.get(app.name, False)) for app in page_obj.object_list],
            }
        )

    def post(self, request, format=None):
        try:
            name = validate_wowza_app_name(request.data.get("name"))
        except ValueError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            schedule_id = validate_wowza_app_name(request.data.get("schedule_id") or name)
        except ValueError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        publish_username = name
        publish_password = generate_wowza_publish_password()

        try:
            payload = WowzaClient().create_live_application(
                name=name,
                storage_user_id=request.user.id,
                schedule_id=schedule_id,
                publish_username=publish_username,
                publish_password=publish_password,
            )
        except WowzaAPIError as exc:
            return Response(
                {
                    "success": False,
                    "message": str(exc),
                    "data": exc.data,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        app, created = WowzaApplication.objects.update_or_create(
            name=name,
            defaults={
                "schedule_id": schedule_id,
                "app_type": "Live",
                "storage_dir": f"{settings.WOWZA_APP_STORAGE_ROOT.rstrip('/')}/{request.user.id}",
                "publish_username": publish_username,
                "publish_password": publish_password,
                "is_active": True,
                "created_by": request.user,
                "response_payload": payload,
            },
        )

        return Response(
            {
                **payload,
                "created_in_mediacms": created,
                "wowza_application": serialize_wowza_application(app),
            },
            status=status.HTTP_201_CREATED,
        )


class WowzaApplicationDetailView(APIView):
    permission_classes = (IsMediacmsAdmin,)
    parser_classes = (JSONParser,)

    def delete(self, request, app_id, format=None):
        app = get_object_or_404(WowzaApplication, id=app_id)
        client = WowzaClient()

        try:
            if app.publish_username:
                try:
                    client.delete_publisher(app_name=app.name, publisher_name=app.publish_username)
                except WowzaAPIError as exc:
                    if exc.status_code != 404:
                        raise
            payload = client.delete_live_application(name=app.name)
        except WowzaAPIError as exc:
            return Response(
                {
                    "success": False,
                    "message": str(exc),
                    "data": exc.data,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        app_name = app.name
        app.delete()
        return Response(
            {
                "success": True,
                "message": f"Aplicación {app_name} eliminada correctamente.",
                "data": payload,
            }
        )


def live_statuses_for_applications(applications):
    client = WowzaClient()
    statuses = {}

    for app in applications:
        try:
            statuses[app.name] = wowza_has_incoming_streams(client.incoming_streams(app_name=app.name))
        except WowzaAPIError:
            statuses[app.name] = False

    return statuses


def serialize_wowza_application(app, *, is_live=False):
    stream_name = settings.WOWZA_PUSH_PUBLISH_STREAM_NAME
    wowza_host = settings.WOWZA_HOST_DEFAULT

    return {
        "id": app.id,
        "name": app.name,
        "schedule_id": app.schedule_id,
        "app_type": app.app_type,
        "storage_dir": app.storage_dir,
        "publish_username": app.publish_username,
        "publish_password": app.publish_password,
        "rtmp_url": f"rtmp://{wowza_host}/{app.name}",
        "stream_name": stream_name,
        "hls_url": f"https://{wowza_host}/{app.name}/{stream_name}/playlist.m3u8",
        "is_live": is_live,
        "is_active": app.is_active,
        "created_by": app.created_by.username if app.created_by else "",
        "add_date": app.add_date.isoformat() if app.add_date else "",
        "update_date": app.update_date.isoformat() if app.update_date else "",
    }


def parse_positive_int(value, *, default):
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return default
    return max(parsed, 1)
