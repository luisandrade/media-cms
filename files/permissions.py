from rest_framework import permissions

from .methods import is_mediacms_editor


class IsMediacmsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))
        )


class IsMediacmsEditor(permissions.BasePermission):
    def has_permission(self, request, view):
        if is_mediacms_editor(request.user):
            return True
        return False
