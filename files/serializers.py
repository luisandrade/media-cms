from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers

from .models import Category, Comment, EncodeProfile, Media, Playlist, Tag, Ads

# TODO: put them in a more DRY way


class MediaSerializer(serializers.ModelSerializer):
    # to be used in APIs as show related media
    user = serializers.ReadOnlyField(source="user.username")
    url = serializers.SerializerMethodField()
    api_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    author_profile = serializers.SerializerMethodField()
    author_thumbnail = serializers.SerializerMethodField()

    def get_url(self, obj):
        return self.context["request"].build_absolute_uri(obj.get_absolute_url())

    def get_api_url(self, obj):
        return self.context["request"].build_absolute_uri(obj.get_absolute_url(api=True))

    def get_thumbnail_url(self, obj):
        if obj.thumbnail_url:
            return self.context["request"].build_absolute_uri(obj.thumbnail_url)
        else:
            return None

    def get_author_profile(self, obj):
        return self.context["request"].build_absolute_uri(obj.author_profile())

    def get_author_thumbnail(self, obj):
        return self.context["request"].build_absolute_uri(obj.author_thumbnail())

    class Meta:
        model = Media
        read_only_fields = (
            "friendly_token",
            "user",
            "add_date",
            "media_type",
            "state",
            "duration",
            "encoding_status",
            "views",
            "likes",
            "dislikes",
            "reported_times",
            "size",
            "is_reviewed",
            "featured",
            "ad_tag"
        )
        fields = (
            "friendly_token",
            "url",
            "api_url",
            "user",
            "title",
            "description",
            "add_date",
            "views",
            "media_type",
            "state",
            "duration",
            "thumbnail_url",
            "is_reviewed",
            "preview_url",
            "author_name",
            "author_profile",
            "author_thumbnail",
            "encoding_status",
            "views",
            "likes",
            "dislikes",
            "reported_times",
            "featured",
            "user_featured",
            "size",
            "ad_tag",
            "hls_file",
            "stream"
        )


class SingleMediaSerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source="user.username")
    url = serializers.SerializerMethodField()
    ads_tag = serializers.SerializerMethodField() 
    download_requires_payment = serializers.SerializerMethodField()
    download_entitled = serializers.SerializerMethodField()
    download_price = serializers.SerializerMethodField()
    download_currency = serializers.SerializerMethodField()
    download_checkout_url = serializers.SerializerMethodField()
    download_options = serializers.SerializerMethodField()
    original_media_url = serializers.SerializerMethodField()

    is_stream = serializers.SerializerMethodField()
    stream = serializers.SerializerMethodField()
    stream_requires_payment = serializers.SerializerMethodField()
    stream_entitled = serializers.SerializerMethodField()
    stream_checkout_url = serializers.SerializerMethodField()


    def get_url(self, obj):
        return self.context["request"].build_absolute_uri(obj.get_absolute_url())

    def get_ads_tag(self, obj):
        if obj.ad_tag:  # usa el campo real
            return {
                "name": obj.ad_tag.name,
                "url": obj.ad_tag.url
            }
        return None

    def _video_download_requires_payment(self, obj) -> bool:
        request = self.context.get("request")
        if not obj.allow_download:
            return False
        if obj.media_type != "video":
            return False
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            # Política: el UI se mostrará, pero no hay entitlement anónimo.
            return bool(getattr(settings, "VIDEO_DOWNLOAD_REQUIRES_PAYMENT", True))
        return bool(getattr(settings, "VIDEO_DOWNLOAD_REQUIRES_PAYMENT", True))

    def _user_entitled(self, obj) -> bool:
        request = self.context.get("request")
        if not request or not getattr(request, "user", None) or not request.user.is_authenticated:
            return False
        if getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False):
            return True
        try:
            from payments.models import DownloadEntitlement

            ent = DownloadEntitlement.objects.filter(user=request.user, media=obj).first()
            if not ent:
                return False
            if ent.status != DownloadEntitlement.STATUS_ACTIVE:
                return False
            if ent.expires_at and ent.expires_at <= timezone.now():
                return False
            return True
        except Exception:
            return False

    def get_download_requires_payment(self, obj):
        return self._video_download_requires_payment(obj)

    def get_download_entitled(self, obj):
        if not self._video_download_requires_payment(obj):
            return True
        return self._user_entitled(obj)

    def get_download_price(self, obj):
        if not self._video_download_requires_payment(obj):
            return None
        return int(getattr(settings, "VIDEO_DOWNLOAD_PRICE_CLP", 990))

    def get_download_currency(self, obj):
        if not self._video_download_requires_payment(obj):
            return None
        return getattr(settings, "VIDEO_DOWNLOAD_CURRENCY", "CLP")

    def get_download_checkout_url(self, obj):
        request = self.context.get("request")
        if not request:
            return None
        if not self._video_download_requires_payment(obj):
            return None
        if self._user_entitled(obj):
            return None
        return request.build_absolute_uri(reverse("video_download_checkout", args=[obj.friendly_token]))

    def get_download_options(self, obj):
        request = self.context.get("request")
        if not request:
            return []

        if obj.media_type != "video" or not obj.allow_download:
            return []

        # Si requiere pago y aún no está habilitado, no entregamos opciones descargables.
        if self._video_download_requires_payment(obj) and not self._user_entitled(obj):
            return []

        items = []
        base_file_url = request.build_absolute_uri(reverse("video_download_file", args=[obj.friendly_token]))

        # Encodings exitosos
        try:
            for encoding in obj.encodings.select_related("profile").filter(chunk=False):
                if encoding.profile and getattr(encoding.profile, "extension", None) == "gif":
                    continue
                if encoding.status != "success" or encoding.progress != 100 or not encoding.media_file:
                    continue
                title = getattr(encoding.profile, "name", "Encoding")
                size = encoding.size or ""
                resolution = getattr(encoding.profile, "resolution", "")
                codec = getattr(encoding.profile, "codec", "")
                label = f"{resolution} - {str(codec).upper()} ({size})".strip()
                items.append(
                    {
                        "itemType": "link",
                        "text": label if label else title,
                        "icon": "arrow_downward",
                        "link": f"{base_file_url}?encoding_id={encoding.id}",
                        "linkAttr": {"target": "_blank", "download": f"{obj.title}_{resolution}_{str(codec).upper()}"},
                    }
                )
        except Exception:
            pass

        # Original
        items.append(
            {
                "itemType": "link",
                "text": f"Original file ({obj.size})" if getattr(obj, "size", None) else "Original file",
                "icon": "arrow_downward",
                "link": f"{base_file_url}?kind=original",
                "linkAttr": {"target": "_blank", "download": obj.title},
            }
        )

        return items

    def get_original_media_url(self, obj):
        # Para videos con descarga pagada, ocultar URL directa del original si no hay entitlement.
        if obj.media_type == "video" and self._video_download_requires_payment(obj) and not self._user_entitled(obj):
            return None
        return obj.original_media_url

    def _stream_playback_requires_payment(self, obj) -> bool:
        request = self.context.get("request")
        if obj.media_type != "video":
            return False
        if not getattr(obj, "stream", ""):
            return False
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return bool(getattr(settings, "VIDEO_STREAM_REQUIRES_PAYMENT", True))
        return bool(getattr(settings, "VIDEO_STREAM_REQUIRES_PAYMENT", True))

    def get_is_stream(self, obj):
        return bool(getattr(obj, "stream", ""))

    def get_stream_requires_payment(self, obj):
        return self._stream_playback_requires_payment(obj)

    def get_stream_entitled(self, obj):
        if not self._stream_playback_requires_payment(obj):
            return True
        return self._user_entitled(obj)

    def get_stream_checkout_url(self, obj):
        request = self.context.get("request")
        if not request:
            return None
        if not self._stream_playback_requires_payment(obj):
            return None
        if self._user_entitled(obj):
            return None
        return request.build_absolute_uri(reverse("video_stream_checkout", args=[obj.friendly_token]))

    def get_stream(self, obj):
        # Para streams pagos, ocultar URL si no hay entitlement.
        if self._stream_playback_requires_payment(obj) and not self._user_entitled(obj):
            return ""
        return getattr(obj, "stream", "")

    class Meta:
        model = Media
        read_only_fields = (
            "friendly_token",
            "user",
            "add_date",
            "views",
            "media_type",
            "state",
            "duration",
            "encoding_status",
            "views",
            "likes",
            "dislikes",
            "reported_times",
            "size",
            "video_height",
            "is_reviewed",
        )
        fields = (
            "url",
            "user",
            "title",
            "description",
            "add_date",
            "edit_date",
            "media_type",
            "state",
            "duration",
            "thumbnail_url",
            "poster_url",
            "thumbnail_time",
            "url",
            "sprites_url",
            "preview_url",
            "author_name",
            "author_profile",
            "author_thumbnail",
            "encodings_info",
            "encoding_status",
            "views",
            "likes",
            "dislikes",
            "reported_times",
            "user_featured",
            "original_media_url",
            "size",
            "video_height",
            "enable_comments",
            "categories_info",
            "is_reviewed",
            "edit_url",
            "tags_info",
            "hls_info",
            "license",
            "subtitles_info",
            "ratings_info",
            "add_subtitle_url",
            "allow_download",
            "download_requires_payment",
            "download_entitled",
            "download_price",
            "download_currency",
            "download_checkout_url",
            "download_options",
            "slideshow_items",
            "ads_tag",
            "hls_file",
            "stream",
            "is_stream",
            "stream_requires_payment",
            "stream_entitled",
            "stream_checkout_url",
        )


class MediaSearchSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    api_url = serializers.SerializerMethodField()

    def get_url(self, obj):
        return self.context["request"].build_absolute_uri(obj.get_absolute_url())

    def get_api_url(self, obj):
        return self.context["request"].build_absolute_uri(obj.get_absolute_url(api=True))

    class Meta:
        model = Media
        fields = (
            "title",
            "author_name",
            "author_profile",
            "thumbnail_url",
            "add_date",
            "views",
            "description",
            "friendly_token",
            "duration",
            "url",
            "api_url",
            "media_type",
            "preview_url",
            "categories_info",
        )


class EncodeProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = EncodeProfile
        fields = ("name", "extension", "resolution", "codec", "description")


class CategorySerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source="user.username")

    class Meta:
        model = Category
        fields = (
            "id",
            "title",
            "description",
            "is_global",
            "media_count",
            "user",
            "thumbnail_url",
        )


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ("title", "media_count", "thumbnail_url")

class AdsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ads
        fields = ("name", "url", "id")


class PlaylistSerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source="user.username")

    class Meta:
        model = Playlist
        read_only_fields = ("add_date", "user")
        fields = ("add_date", "title", "description", "user", "media_count", "url", "api_url", "thumbnail_url")


class PlaylistDetailSerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source="user.username")

    class Meta:
        model = Playlist
        read_only_fields = ("add_date", "user")
        fields = ("title", "add_date", "user_thumbnail_url", "description", "user", "media_count", "url", "thumbnail_url")


class CommentSerializer(serializers.ModelSerializer):
    author_profile = serializers.ReadOnlyField(source="user.get_absolute_url")
    author_name = serializers.ReadOnlyField(source="user.name")
    author_thumbnail_url = serializers.ReadOnlyField(source="user.thumbnail_url")

    class Meta:
        model = Comment
        read_only_fields = ("add_date", "uid")
        fields = (
            "add_date",
            "text",
            "parent",
            "author_thumbnail_url",
            "author_profile",
            "author_name",
            "media_url",
            "uid",
        )
