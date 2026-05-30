from drf_yasg import openapi as openapi
from drf_yasg.utils import swagger_auto_schema
from django.db.utils import OperationalError, ProgrammingError
from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView

from users.models import User
from users.serializers import UserSerializer
from payments.models import Payment

from .methods import is_mediacms_manager
from .models import Category, Comment, Media
from .permissions import IsMediacmsEditor
from .serializers import CommentSerializer, MediaSerializer


class StatisticsView(APIView):
    """Statistics for admin dashboard cards."""

    permission_classes = (IsMediacmsEditor,)
    parser_classes = (JSONParser,)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Manage'],
        operation_summary='Manage Statistics',
        operation_description='Summary statistics for MediaCMS management pages',
    )
    def get(self, request, format=None):
        try:
            total_sales = Payment.objects.filter(status=Payment.STATUS_PAID).count()
        except (OperationalError, ProgrammingError):
            total_sales = 0

        top_categories = [
            {
                "title": category.title,
                "url": category.get_absolute_url(),
                "media_count": category.media_count,
            }
            for category in Category.objects.order_by("-media_count", "title")[:6]
        ]

        recent_activity = []

        for media in Media.objects.select_related("user").order_by("-add_date")[:5]:
            recent_activity.append(
                {
                    "kind": "media",
                    "user_name": media.user.name or media.user.username,
                    "user_email": media.user.email,
                    "user_thumbnail": media.user.thumbnail_url(),
                    "media_title": media.title,
                    "status": "Approved" if media.is_reviewed and media.state == "public" else "Pending",
                    "date": media.add_date,
                }
            )

        for comment in Comment.objects.select_related("user", "media").order_by("-add_date")[:5]:
            recent_activity.append(
                {
                    "kind": "comment",
                    "user_name": comment.user.name or comment.user.username,
                    "user_email": comment.user.email,
                    "user_thumbnail": comment.user.thumbnail_url(),
                    "media_title": comment.media.title,
                    "status": "Approved" if comment.media.is_reviewed and comment.media.state == "public" else "Pending",
                    "date": comment.add_date,
                }
            )

        recent_activity = sorted(recent_activity, key=lambda item: item["date"], reverse=True)[:5]

        top_rated_videos = []
        for index, media in enumerate(
            Media.objects.filter(media_type="video")
            .prefetch_related("category")
            .order_by("-likes", "-views", "title")[:5],
            start=1,
        ):
            primary_category = media.category.order_by("title").first()
            top_rated_videos.append(
                {
                    "rank": index,
                    "title": media.title,
                    "url": media.get_absolute_url(),
                    "thumbnail_url": media.poster_url or media.thumbnail_url,
                    "year": media.add_date.year if media.add_date else None,
                    "category": primary_category.title if primary_category else "",
                    "views": media.views,
                    "likes": media.likes,
                }
            )

        return Response(
            {
                "total_videos": Media.objects.filter(media_type="video").count(),
                "total_members": User.objects.count(),
                "total_categories": Category.objects.count(),
                "total_sales": total_sales,
                "top_categories": top_categories,
                "recent_activity": recent_activity,
                "top_rated_videos": top_rated_videos,
            }
        )


class MediaList(APIView):
    """Media listings
    Used on management pages of MediaCMS
    Should be available only to MediaCMS editors,
    managers and admins
    """

    permission_classes = (IsMediacmsEditor,)
    parser_classes = (JSONParser,)

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name='sort_by', type=openapi.TYPE_STRING, in_=openapi.IN_QUERY, description='Sort by any of: title, add_date, edit_date, views, likes, reported_times'),
            openapi.Parameter(name='ordering', type=openapi.TYPE_STRING, in_=openapi.IN_QUERY, description='Order by: asc, desc'),
            openapi.Parameter(name='state', type=openapi.TYPE_STRING, in_=openapi.IN_QUERY, description='Media state, options: private", "public", "unlisted'),
            openapi.Parameter(name='encoding_status', type=openapi.TYPE_STRING, in_=openapi.IN_QUERY, description='Encoding status, options "pending", "running", "fail", "success"'),
        ],
        tags=['Manage'],
        operation_summary='Manage Media',
        operation_description='Manage media for MediaCMS managers and reviewers',
    )
    def get(self, request, format=None):
        params = self.request.query_params
        ordering = params.get("ordering", "").strip()
        sort_by = params.get("sort_by", "").strip()
        state = params.get("state", "").strip()
        encoding_status = params.get("encoding_status", "").strip()
        media_type = params.get("media_type", "").strip()

        featured = params.get("featured", "").strip()
        is_reviewed = params.get("is_reviewed", "").strip()
        category = params.get("category", "").strip()

        sort_by_options = [
            "title",
            "add_date",
            "edit_date",
            "views",
            "likes",
            "reported_times",
        ]
        if sort_by not in sort_by_options:
            sort_by = "add_date"
        if ordering == "asc":
            ordering = ""
        else:
            ordering = "-"

        if media_type not in ["video", "image", "audio", "pdf"]:
            media_type = None

        if state not in ["private", "public", "unlisted"]:
            state = None

        if encoding_status not in ["pending", "running", "fail", "success"]:
            encoding_status = None

        if featured == "true":
            featured = True
        elif featured == "false":
            featured = False
        else:
            featured = "all"
        if is_reviewed == "true":
            is_reviewed = True
        elif is_reviewed == "false":
            is_reviewed = False
        else:
            is_reviewed = "all"

        pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
        qs = Media.objects.filter()
        if state:
            qs = qs.filter(state=state)
        if encoding_status:
            qs = qs.filter(encoding_status=encoding_status)
        if media_type:
            qs = qs.filter(media_type=media_type)

        if featured != "all":
            qs = qs.filter(featured=featured)
        if is_reviewed != "all":
            qs = qs.filter(is_reviewed=is_reviewed)
        if category:
            qs = qs.filter(category__title__contains=category)

        media = qs.order_by(f"{ordering}{sort_by}")

        paginator = pagination_class()

        page = paginator.paginate_queryset(media, request)

        serializer = MediaSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Manage'],
        operation_summary='Delete Media',
        operation_description='Delete media for MediaCMS managers and reviewers',
    )
    def delete(self, request, format=None):
        tokens = request.GET.get("tokens")
        if tokens:
            tokens = tokens.split(",")
            Media.objects.filter(friendly_token__in=tokens).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommentList(APIView):
    """Comments listings
    Used on management pages of MediaCMS
    Should be available only to MediaCMS editors,
    managers and admins
    """

    permission_classes = (IsMediacmsEditor,)
    parser_classes = (JSONParser,)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Manage'],
        operation_summary='Manage Comments',
        operation_description='Manage comments for MediaCMS managers and reviewers',
    )
    def get(self, request, format=None):
        params = self.request.query_params
        ordering = params.get("ordering", "").strip()
        sort_by = params.get("sort_by", "").strip()

        sort_by_options = ["text", "add_date"]
        if sort_by not in sort_by_options:
            sort_by = "add_date"
        if ordering == "asc":
            ordering = ""
        else:
            ordering = "-"

        pagination_class = api_settings.DEFAULT_PAGINATION_CLASS

        qs = Comment.objects.filter()
        media = qs.order_by(f"{ordering}{sort_by}")

        paginator = pagination_class()

        page = paginator.paginate_queryset(media, request)

        serializer = CommentSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Manage'],
        operation_summary='Delete Comments',
        operation_description='Delete comments for MediaCMS managers and reviewers',
    )
    def delete(self, request, format=None):
        comment_ids = request.GET.get("comment_ids")
        if comment_ids:
            comments = comment_ids.split(",")
            Comment.objects.filter(uid__in=comments).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserList(APIView):
    """Users listings
    Used on management pages of MediaCMS
    Should be available only to MediaCMS editors,
    managers and admins. Delete should be option
    for managers+admins only.
    """

    permission_classes = (IsMediacmsEditor,)
    parser_classes = (JSONParser,)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Manage'],
        operation_summary='Manage Users',
        operation_description='Manage users for MediaCMS managers and reviewers',
    )
    def get(self, request, format=None):
        params = self.request.query_params
        ordering = params.get("ordering", "").strip()
        sort_by = params.get("sort_by", "").strip()
        role = params.get("role", "all").strip()

        sort_by_options = ["date_added", "name"]
        if sort_by not in sort_by_options:
            sort_by = "date_added"
        if ordering == "asc":
            ordering = ""
        else:
            ordering = "-"

        pagination_class = api_settings.DEFAULT_PAGINATION_CLASS

        qs = User.objects.filter()
        if role == "manager":
            qs = qs.filter(is_manager=True)
        elif role == "editor":
            qs = qs.filter(is_editor=True)

        users = qs.order_by(f"{ordering}{sort_by}")

        paginator = pagination_class()

        page = paginator.paginate_queryset(users, request)

        serializer = UserSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Manage'],
        operation_summary='Delete Users',
        operation_description='Delete users for MediaCMS managers',
    )
    def delete(self, request, format=None):
        if not is_mediacms_manager(request.user):
            return Response({"detail": "bad permissions"}, status=status.HTTP_400_BAD_REQUEST)

        tokens = request.GET.get("tokens")
        if tokens:
            tokens = tokens.split(",")
            User.objects.filter(username__in=tokens).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
