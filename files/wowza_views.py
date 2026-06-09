from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsMediacmsAdmin
from .wowza import WowzaAPIError, WowzaClient, validate_wowza_app_name


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

    def post(self, request, format=None):
        try:
            name = validate_wowza_app_name(request.data.get("name"))
        except ValueError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            schedule_id = validate_wowza_app_name(request.data.get("schedule_id") or name)
        except ValueError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payload = WowzaClient().create_live_application(
                name=name,
                storage_user_id=request.user.id,
                schedule_id=schedule_id,
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

        return Response(payload, status=status.HTTP_201_CREATED)
