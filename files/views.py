from datetime import datetime, timedelta
from functools import wraps
import logging
from urllib.parse import parse_qsl, urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import SearchQuery
from django.core.mail import EmailMessage
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from drf_yasg import openapi as openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import (
    FileUploadParser,
    FormParser,
    JSONParser,
    MultiPartParser,
)
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView

from actions.models import USER_MEDIA_ACTIONS, MediaAction
from cms.custom_pagination import FastPaginationWithoutCount
from cms.permissions import (
    IsAuthorizedToAdd,
    IsAuthorizedToAddComment,
    IsUserOrEditor,
    user_allowed_to_upload,
)
from users.models import User

from .forms import ContactForm, EditSubtitleForm, MediaForm, SubtitleForm, AdsForm
from .frontend_translations import translate_string
from .helpers import clean_query, get_alphanumeric_only, produce_ffmpeg_commands
from .methods import (
    check_comment_for_mention,
    create_video_trim_request,
    get_user_or_session,
    is_mediacms_editor,
    is_mediacms_manager,
    list_tasks,
    notify_user_on_comment,
    show_recommended_media,
    show_related_media,
    update_user_ratings,
)
from .models import (
    Category,
    Comment,
    EncodeProfile,
    Encoding,
    Media,
    Playlist,
    PlaylistMedia,
    Subtitle,
    Tag,
    VideoTrimRequest,
    WowzaApplication,
    Ads
)
from .serializers import (
    CategorySerializer,
    CommentSerializer,
    EncodeProfileSerializer,
    MediaSearchSerializer,
    MediaSerializer,
    PlaylistDetailSerializer,
    PlaylistSerializer,
    SingleMediaSerializer,
    TagSerializer,
    AdsSerializer
)
from .storage_usage import STORAGE_LIMIT_MESSAGE, media_storage_has_capacity
from .stop_words import STOP_WORDS
from .tasks import save_user_action, video_trim_task
import json

from . import cdn_balancer as cdn_balancer_module
from .cdn_balancer import get_balanced_hosts_for_request
from .wowza import generate_wowza_token

logger = logging.getLogger(__name__)

VALID_USER_ACTIONS = [action for action, name in USER_MEDIA_ACTIONS]


def _user_requires_active_subscription_for_media_access(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return not is_mediacms_editor(user)


def _user_has_media_access(user) -> bool:
    if not _user_requires_active_subscription_for_media_access(user):
        return True

    try:
        from payments.models import user_has_active_subscription

        return user_has_active_subscription(user)
    except Exception:
        return False


def _subscription_required_context() -> dict:
    try:
        subscription_url = reverse("subscription_portal")
    except Exception:
        subscription_url = "/subscriptions/"
    return {"subscription_portal_url": subscription_url}

def portal_login_required(view_func):
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if getattr(settings, "GLOBAL_LOGIN_REQUIRED", False):
            return login_required(view_func)(request, *args, **kwargs)
        return view_func(request, *args, **kwargs)

    return wrapped_view


@portal_login_required
def about(request):
    """About view"""

    context = {}
    return render(request, "cms/about.html", context)

@portal_login_required
def stats(request):
    """About view"""

    context = {}
    return render(request, "cms/stats.html", context)

@portal_login_required
def setlanguage(request):
    """Set Language view"""

    context = {}
    return render(request, "cms/set_language.html", context)


@portal_login_required
def add_subtitle(request):
    """Add subtitle view"""

    friendly_token = request.GET.get("m", "").strip()
    if not friendly_token:
        return HttpResponseRedirect("/")
    media = Media.objects.filter(friendly_token=friendly_token).first()
    if not media:
        return HttpResponseRedirect("/")

    if not (request.user == media.user or is_mediacms_editor(request.user) or is_mediacms_manager(request.user)):
        return HttpResponseRedirect("/")

    if request.method == "POST":
        form = SubtitleForm(media, request.POST, request.FILES)
        if form.is_valid():
            subtitle = form.save()
            new_subtitle = Subtitle.objects.filter(id=subtitle.id).first()
            try:
                new_subtitle.convert_to_srt()
                messages.add_message(request, messages.INFO, translate_string(request.LANGUAGE_CODE, "Subtitle was added"))
                return HttpResponseRedirect(subtitle.media.get_absolute_url())
            except:  # noqa: E722
                new_subtitle.delete()
                error_msg = "Formato de subtítulo inválido. Usa archivos SubRip (.srt) o WebVTT (.vtt)."
                form.add_error("subtitle_file", error_msg)

    else:
        form = SubtitleForm(media_item=media)
    subtitles = media.subtitles.all()
    context = {"media": media, "form": form, "subtitles": subtitles}
    return render(request, "cms/add_subtitle.html", context)


@portal_login_required
def edit_subtitle(request):
    subtitle_id = request.GET.get("id", "").strip()
    action = request.GET.get("action", "").strip()
    if not subtitle_id:
        return HttpResponseRedirect("/")
    subtitle = Subtitle.objects.filter(id=subtitle_id).first()

    if not subtitle:
        return HttpResponseRedirect("/")

    if not (request.user == subtitle.user or is_mediacms_editor(request.user) or is_mediacms_manager(request.user)):
        return HttpResponseRedirect("/")

    context = {"subtitle": subtitle, "action": action}

    if action == "download":
        response = HttpResponse(subtitle.subtitle_file.read(), content_type="text/vtt")
        filename = subtitle.subtitle_file.name.split("/")[-1]

        if not filename.endswith(".vtt"):
            filename = f"{filename}.vtt"

        response["Content-Disposition"] = f"attachment; filename={filename}"  # noqa

        return response

    if request.method == "GET":
        form = EditSubtitleForm(subtitle)
        context["form"] = form
    elif request.method == "POST":
        confirm = request.GET.get("confirm", "").strip()
        if confirm == "true":
            messages.add_message(request, messages.INFO, translate_string(request.LANGUAGE_CODE, "Subtitle was deleted"))
            redirect_url = subtitle.media.get_absolute_url()
            subtitle.delete()
            return HttpResponseRedirect(redirect_url)
        form = EditSubtitleForm(subtitle, request.POST)
        subtitle_text = form.data["subtitle"]
        with open(subtitle.subtitle_file.path, "w") as ff:
            ff.write(subtitle_text)

        messages.add_message(request, messages.INFO, translate_string(request.LANGUAGE_CODE, "Subtitle was edited"))
        return HttpResponseRedirect(subtitle.media.get_absolute_url())
    return render(request, "cms/edit_subtitle.html", context)

@portal_login_required
def categories(request):
    """List categories view"""

    context = {}
    return render(request, "cms/categories.html", context)

@portal_login_required
def create_add_ads_tag(request):
    error = None

    if request.method == 'POST':
        form = AdsForm(request.POST)
        if form.is_valid():
            ad = form.save()
            return redirect('ads')
        else:
            error = "Corrige los errores del formulario."
    else:
        form = AdsForm()

    context = {
        'form': form,
        'error': error,
    }
    return render(request, "cms/ads.html", context)
@portal_login_required
def contact(request):
    """Contact view"""

    context = {}
    if request.method == "GET":
        form = ContactForm(request.user)
        context["form"] = form

    else:
        form = ContactForm(request.user, request.POST)
        if form.is_valid():
            if request.user.is_authenticated:
                from_email = request.user.email
                name = request.user.name
            else:
                from_email = request.POST.get("from_email")
                name = request.POST.get("name")
            message = request.POST.get("message")

            title = "[{}] - Mensaje recibido del formulario de contacto".format(settings.PORTAL_NAME)

            msg = """
            Has recibido un mensaje a través del formulario de contacto\n
            Nombre del remitente: %s
            Correo del remitente: %s\n
            \n %s
            """ % (
                name,
                from_email,
                message,
            )
            email = EmailMessage(
                msg,
                settings.DEFAULT_FROM_EMAIL,
                settings.ADMIN_EMAIL_LIST,
                reply_to=[from_email],
            )
            email.send(fail_silently=True)
            context["success_msg"] = success_msg

    return render(request, "cms/contact.html", context)

@portal_login_required
def history(request):
    """Show personal history view"""

    context = {}
    return render(request, "cms/history.html", context)


@portal_login_required
def purchases(request):
    """Show personal purchases view"""

    context = {}
    return render(request, "cms/purchases.html", context)


@portal_login_required
def edit_media(request):
    """Edit a media view"""

    friendly_token = request.GET.get("m", "").strip()
    if not friendly_token:
        return HttpResponseRedirect("/")
    media = Media.objects.filter(friendly_token=friendly_token).first()

    if not media:
        return HttpResponseRedirect("/")

    if not (request.user == media.user or is_mediacms_editor(request.user) or is_mediacms_manager(request.user)):
        return HttpResponseRedirect("/")
    if request.method == "POST":
        form = MediaForm(request.user, request.POST, request.FILES, instance=media)
        if form.is_valid():
            media = form.save()
            for tag in media.tags.all():
                media.tags.remove(tag)
            if form.cleaned_data.get("new_tags"):
                for tag in form.cleaned_data.get("new_tags").split(","):
                    tag = get_alphanumeric_only(tag)
                    tag = tag[:99]
                    if tag:
                        try:
                            tag = Tag.objects.get(title=tag)
                        except Tag.DoesNotExist:
                            tag = Tag.objects.create(title=tag, user=request.user)
                        if tag not in media.tags.all():
                            media.tags.add(tag)
            messages.add_message(request, messages.INFO, translate_string(request.LANGUAGE_CODE, "Media was edited"))
            return HttpResponseRedirect(media.get_absolute_url())
    else:
        form = MediaForm(request.user, instance=media)
    return render(
        request,
        "cms/edit_media.html",
        {
            "form": form,
            "media_object": media,
            "add_subtitle_url": media.add_subtitle_url,
            "allow_video_trimmer": settings.ALLOW_VIDEO_TRIMMER,
        },
    )

@csrf_exempt
@portal_login_required
def trim_video(request, friendly_token):
    if not settings.ALLOW_VIDEO_TRIMMER:
        return JsonResponse({"success": False, "error": "Video trimming is not allowed"}, status=400)

    if request.method != "POST":
        return HttpResponseRedirect("/")

    media = Media.objects.filter(friendly_token=friendly_token).first()
    if not media:
        return HttpResponseRedirect("/")

    if not (request.user == media.user or is_mediacms_editor(request.user) or is_mediacms_manager(request.user)):
        return HttpResponseRedirect("/")

    existing_requests = VideoTrimRequest.objects.filter(media=media, status__in=["initial", "running"]).exists()
    if existing_requests:
        return JsonResponse({"success": False, "error": "A trim request is already in progress for this video"}, status=400)

    try:
        data = json.loads(request.body)
        video_trim_request = create_video_trim_request(media, data)
        video_trim_task.delay(video_trim_request.id)
        return JsonResponse({"success": True, "request_id": video_trim_request.id}, status=200)
    except Exception:
        return JsonResponse({"success": False, "error": "Incorrect request data"}, status=400)


@portal_login_required
def edit_video(request):
    friendly_token = request.GET.get("m", "").strip()
    if not friendly_token:
        return HttpResponseRedirect("/")

    media = Media.objects.filter(friendly_token=friendly_token).first()
    if not media:
        return HttpResponseRedirect("/")

    if not (request.user == media.user or is_mediacms_editor(request.user) or is_mediacms_manager(request.user)):
        return HttpResponseRedirect("/")

    if media.media_type != "video":
        messages.add_message(request, messages.INFO, "Media is not video")
        return HttpResponseRedirect(media.get_absolute_url())

    if not settings.ALLOW_VIDEO_TRIMMER:
        messages.add_message(request, messages.INFO, "Video Trimmer is not enabled")
        return HttpResponseRedirect(media.get_absolute_url())

    running_trim_request = VideoTrimRequest.objects.filter(media=media, status__in=["initial", "running"]).exists()
    if running_trim_request:
        messages.add_message(request, messages.INFO, "Video trim request is already running")
        return HttpResponseRedirect(media.get_absolute_url())

    media_file_path = media.trim_video_url
    if not media_file_path:
        messages.add_message(request, messages.INFO, "No MP4 source is available for the video trimmer yet")
        return HttpResponseRedirect(media.get_absolute_url())

    if media.encoding_status in ["pending", "running"]:
        messages.add_message(request, messages.INFO, "Media encoding has not finished yet. Showing the best available source")

    return render(
        request,
        "cms/edit_video.html",
        {
            "media_object": media,
            "media_file_path": media_file_path,
            "allow_video_trimmer": settings.ALLOW_VIDEO_TRIMMER,
        },
    )

def _build_local_vod_playback_urls(media):
    hls_master_file = ""
    try:
        hls_master_file = ((getattr(media, "hls_info", {}) or {}).get("master_file") or "").strip()
    except Exception:
        hls_master_file = ""

    if hls_master_file:
        return {"vod": {"url": hls_master_file, "token": None}}

    original_media_url = (getattr(media, "original_media_url", None) or "").strip()
    if original_media_url:
        return {"vod": {"url": original_media_url, "token": None}}

    return {}


def _playback_debug_info(playback_urls, *, media, balanced):
    urls = {}
    for key, entry in (playback_urls or {}).items():
        if key == "_balancer" or not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if url:
            urls[key] = url

    playback_url = urls.get("vod") or next(iter(urls.values()), "")
    playback_kind = "live" if getattr(media, "stream", "") else "vod"
    return {
        "playback_kind": playback_kind,
        "playback_url": playback_url,
        "playback_urls": urls,
        "client_ip": balanced.client_ip,
        "asn": balanced.asn,
        "city": balanced.city,
        "vod_host": balanced.vod_host,
        "live_host": balanced.live_host,
        "decision": balanced.decision,
    }


def embed_media(request):
    from django.shortcuts import redirect, render
    from .models import Media

    friendly_token = request.GET.get("m", "").strip()
    if not friendly_token:
        return redirect("/")

    media = Media.objects.filter(friendly_token=friendly_token).first()
    if not media:
        return redirect("/")

    balanced = get_balanced_hosts_for_request(request)
    live_host = balanced.live_host
    vod_host = balanced.vod_host

    secret_live = getattr(settings, "WOWZA_LIVE_SECRET", "c1bcbdc0c1eac962")
    token_name = getattr(settings, "WOWZA_TOKEN_NAME", "wowzatoken")
    client_ip = None
    start = 0
    end = 0

    playback_urls = {}

    balancer_debug = (
        str(request.GET.get("balancer_debug", "")).strip().lower() in {"1", "true", "yes", "y", "on"}
        or bool(getattr(settings, "CDN_BALANCER_DEBUG", False))
    )

    def _user_entitled_for_stream() -> bool:
        if not getattr(media, "stream", ""):
            return True
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return False
        try:
            from payments.models import DownloadEntitlement

            ent = DownloadEntitlement.objects.filter(user=request.user, media=media).first()
            if not ent:
                return False
            if ent.status != DownloadEntitlement.STATUS_ACTIVE:
                return False
            if ent.expires_at and ent.expires_at <= timezone.now():
                return False
            return True
        except Exception:
            return False

    stream_requires_payment = bool(getattr(settings, "VIDEO_STREAM_REQUIRES_PAYMENT", True))

    # ES STREAM
    if media.stream:
        if stream_requires_payment and not _user_entitled_for_stream():
            playback_urls = {}
        else:
            stream_names = getattr(settings, "WOWZA_STREAM_NAMES", ["default_stream"])
            for name in stream_names:
                stream_path = f"{name}/live"
                token = generate_wowza_token(
                    stream_path,
                    secret_live,
                    token_name=token_name,
                    client_ip=client_ip,
                    start=start,
                    end=end,
                )
                url = f"https://{live_host}/{stream_path}/playlist.m3u8?{token}"
                playback_urls[name] = {
                    "url": url,
                    "token": token,
                }
    else:
        if bool(getattr(settings, "VIDEO_PLAYBACK_USE_LOCAL_URLS", False)):
            playback_urls = _build_local_vod_playback_urls(media)
        else:
            vod_template = getattr(
                settings,
                "WOWZA_VOD_SMIL_PATH_TEMPLATE",
                "mediavms-development/smil:{media_id}.smil/playlist.m3u8",
            )
            vod_path = vod_template.format(media_id=friendly_token)
            playback_urls["vod"] = {
                "url": f"https://{vod_host}/{vod_path}",
                "token": None,
            }

    playback_debug = None
    if balancer_debug:
        playback_debug = _playback_debug_info(playback_urls, media=media, balanced=balanced)
        playback_urls["_balancer"] = {
            **playback_debug,
            "meta": {
                "remote_addr": request.META.get("REMOTE_ADDR"),
                "x_forwarded_for": request.META.get("HTTP_X_FORWARDED_FOR"),
                "x_real_ip": request.META.get("HTTP_X_REAL_IP"),
                "cf_connecting_ip": request.META.get("HTTP_CF_CONNECTING_IP"),
                "true_client_ip": request.META.get("HTTP_TRUE_CLIENT_IP"),
            },
            "geoip": {
                "enabled": bool(getattr(settings, "CDN_BALANCER_ENABLED", True)),
                "geoip2_available": cdn_balancer_module.geoip2 is not None,
                "city_db_path": getattr(settings, "CDN_BALANCER_CITY_DB_PATH", ""),
                "asn_db_path": getattr(settings, "CDN_BALANCER_ASN_DB_PATH", ""),
            },
        }
        logger.info(
            "cdn_balancer embed ip=%s asn=%s city=%s vod=%s live=%s decision=%s",
            balanced.client_ip,
            balanced.asn,
            balanced.city,
            vod_host,
            live_host,
            balanced.decision,
        )

    return render(request, "cms/embed.html", {
        "media": friendly_token,
        "playback_urls": json.dumps(playback_urls),
        "balancer_debug": balancer_debug,
        "playback_debug": json.dumps(playback_debug, indent=2, ensure_ascii=False) if playback_debug else "",
    })

@portal_login_required
def featured_media(request):
    """List featured media view"""

    context = {}
    return render(request, "cms/featured-media.html", context)

@portal_login_required
def index(request):
    """Index view"""

    context = {}
    return render(request, "cms/index.html", context)

@portal_login_required
def latest_media(request):
    """List latest media view"""

    context = {}
    return render(request, "cms/latest-media.html", context)

@portal_login_required
def liked_media(request):
    """List user's liked media view"""

    context = {}
    return render(request, "cms/liked_media.html", context)


@portal_login_required
def manage_users(request):
    """List users management view"""

    context = {}
    return render(request, "cms/manage_users.html", context)


@portal_login_required
def manage_wowza(request):
    """Wowza management view."""

    if not (request.user.is_superuser or request.user.is_staff):
        return HttpResponse("Forbidden", status=403)

    context = {}
    return render(request, "cms/manage_wowza.html", context)


@portal_login_required
def manage_media(request):
    """List media management view"""

    categories = Category.objects.all().order_by("title").values_list("title", flat=True)
    context = {"categories": list(categories)}
    return render(request, "cms/manage_media.html", context)


@portal_login_required
def manage_comments(request):
    """List comments management view"""

    context = {}
    return render(request, "cms/manage_comments.html", context)


@portal_login_required
def manage_statistics(request):
    """Management statistics view"""

    context = {}
    return render(request, "cms/manage_statistics.html", context)

@portal_login_required
def members(request):
    """List members view"""

    context = {}
    return render(request, "cms/members.html", context)

@portal_login_required
def recommended_media(request):
    """List recommended media view"""

    context = {}
    return render(request, "cms/recommended-media.html", context)


@portal_login_required
def search(request):
    """Search view"""

    context = {}
    RSS_URL = f"/rss{request.environ.get('REQUEST_URI')}"
    context["RSS_URL"] = RSS_URL
    return render(request, "cms/search.html", context)


def sitemap(request):
    """Sitemap"""

    context = {}
    context["media"] = list(Media.objects.filter(Q(listable=True)).order_by("-add_date"))
    context["playlists"] = list(Playlist.objects.filter().order_by("-add_date"))
    context["users"] = list(User.objects.filter())
    return render(request, "sitemap.xml", context, content_type="application/xml")

@portal_login_required
def tags(request):
    """List tags view"""

    context = {}
    return render(request, "cms/tags.html", context)


@portal_login_required
def tos(request):
    """Terms of service view"""

    context = {}
    return render(request, "cms/tos.html", context)

@portal_login_required
def upload_media(request):
    """Upload media view"""

    from allauth.account.forms import LoginForm

    form = LoginForm()
    context = {}
    context["form"] = form
    context["can_add"] = user_allowed_to_upload(request)
    can_upload_exp = STORAGE_LIMIT_MESSAGE if not media_storage_has_capacity() else settings.CANNOT_ADD_MEDIA_MESSAGE
    context["can_upload_exp"] = can_upload_exp

    return render(request, "cms/add-media.html", context)

@portal_login_required
def view_media(request):
    """View media view"""
    import hashlib, base64
    from django.conf import settings

    if _user_requires_active_subscription_for_media_access(request.user) and not _user_has_media_access(request.user):
        return render(request, "cms/subscription_required.html", _subscription_required_context(), status=403)

    friendly_token = request.GET.get("m", "").strip()
    context = {}
    media = Media.objects.filter(friendly_token=friendly_token).first()
    if not media:
        context["media"] = None
        return render(request, "cms/media.html", context)

    # Registro de acción de visualización
    user_or_session = get_user_or_session(request)
    save_user_action.delay(user_or_session, friendly_token=friendly_token, action="watch")

    context["media"] = friendly_token
    context["media_object"] = media

    context["CAN_DELETE_MEDIA"] = False
    context["CAN_EDIT_MEDIA"] = False
    context["CAN_DELETE_COMMENTS"] = False

    if request.user.is_authenticated:
        if (media.user.id == request.user.id) or is_mediacms_editor(request.user) or is_mediacms_manager(request.user):
            context["CAN_DELETE_MEDIA"] = True
            context["CAN_EDIT_MEDIA"] = True
            context["CAN_DELETE_COMMENTS"] = True

    # 🔐 Token Wowza + CDN balancer
    balanced = get_balanced_hosts_for_request(request)
    live_host = balanced.live_host
    vod_host = balanced.vod_host

    secret_live = getattr(settings, "WOWZA_LIVE_SECRET", "c1bcbdc0c1eac962")
    token_name = getattr(settings, "WOWZA_TOKEN_NAME", "wowzatoken")
    client_ip = None
    start = 0
    end = 0

    playback_urls = {}

    balancer_debug = (
        str(request.GET.get("balancer_debug", "")).strip().lower() in {"1", "true", "yes", "y", "on"}
        or bool(getattr(settings, "CDN_BALANCER_DEBUG", False))
    )

    def _user_entitled_for_stream() -> bool:
        if not getattr(media, "stream", ""):
            return True
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return False
        try:
            from payments.models import DownloadEntitlement

            ent = DownloadEntitlement.objects.filter(user=request.user, media=media).first()
            if not ent:
                return False
            if ent.status != DownloadEntitlement.STATUS_ACTIVE:
                return False
            if ent.expires_at and ent.expires_at <= timezone.now():
                return False
            return True
        except Exception:
            return False

    stream_requires_payment = bool(getattr(settings, "VIDEO_STREAM_REQUIRES_PAYMENT", True))

    if media.stream:
        if stream_requires_payment and not _user_entitled_for_stream():
            playback_urls = {}
        else:
            stream_names = getattr(settings, "WOWZA_STREAM_NAMES", ["default_stream"])
            for name in stream_names:
                stream_path = f"{name}/live"
                token = generate_wowza_token(
                    stream_path,
                    secret_live,
                    token_name=token_name,
                    client_ip=client_ip,
                    start=start,
                    end=end,
                )
                playback_urls[name] = {
                    "url": f"https://{live_host}/{stream_path}/playlist.m3u8?{token}",
                    "token": token,
                }
    else:
        if bool(getattr(settings, "VIDEO_PLAYBACK_USE_LOCAL_URLS", False)):
            playback_urls = _build_local_vod_playback_urls(media)
        else:
            vod_template = getattr(
                settings,
                "WOWZA_VOD_SMIL_PATH_TEMPLATE",
                "mediavms-development/smil:{media_id}.smil/playlist.m3u8",
            )
            vod_path = vod_template.format(media_id=friendly_token)
            playback_urls["vod"] = {
                "url": f"https://{vod_host}/{vod_path}",
                "token": None,
            }

    playback_debug = None
    if balancer_debug:
        playback_debug = _playback_debug_info(playback_urls, media=media, balanced=balanced)
        playback_urls["_balancer"] = {
            **playback_debug,
            "meta": {
                "remote_addr": request.META.get("REMOTE_ADDR"),
                "x_forwarded_for": request.META.get("HTTP_X_FORWARDED_FOR"),
                "x_real_ip": request.META.get("HTTP_X_REAL_IP"),
                "cf_connecting_ip": request.META.get("HTTP_CF_CONNECTING_IP"),
                "true_client_ip": request.META.get("HTTP_TRUE_CLIENT_IP"),
            },
            "geoip": {
                "enabled": bool(getattr(settings, "CDN_BALANCER_ENABLED", True)),
                "geoip2_available": cdn_balancer_module.geoip2 is not None,
                "city_db_path": getattr(settings, "CDN_BALANCER_CITY_DB_PATH", ""),
                "asn_db_path": getattr(settings, "CDN_BALANCER_ASN_DB_PATH", ""),
            },
        }
        logger.info(
            "cdn_balancer view ip=%s asn=%s city=%s vod=%s live=%s decision=%s",
            balanced.client_ip,
            balanced.asn,
            balanced.city,
            vod_host,
            live_host,
            balanced.decision,
        )

    context["playback_urls"] = json.dumps(playback_urls)  # ✅ Aquí se agrega al contexto
    context["balancer_debug"] = balancer_debug
    context["playback_debug"] = json.dumps(playback_debug, indent=2, ensure_ascii=False) if playback_debug else ""

    return render(request, "cms/media.html", context)

@portal_login_required
def view_playlist(request, friendly_token):
    """View playlist view"""

    try:
        playlist = Playlist.objects.get(friendly_token=friendly_token)
    except BaseException:
        playlist = None

    context = {}
    context["playlist"] = playlist
    return render(request, "cms/playlist.html", context)


@login_required
def view_wowza_live(request, app_name):
    """View Wowza live application with subscription gating."""

    if _user_requires_active_subscription_for_media_access(request.user) and not _user_has_media_access(request.user):
        return render(request, "cms/subscription_required.html", _subscription_required_context(), status=403)

    app = get_object_or_404(WowzaApplication, name=app_name, is_active=True)

    from .wowza_views import hls_url_for_application, live_statuses_for_applications
    from .live_chat import user_can_moderate_live_chat, user_can_write_live_chat

    is_live = live_statuses_for_applications([app]).get(app.name, False)
    debug_hls_url = hls_url_for_application(app.name)
    parsed_hls_url = urlparse(debug_hls_url)
    show_wowza_debug = bool(getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False))
    force_debug_player = show_wowza_debug and str(request.GET.get("debug_player", "1")).lower() not in {"0", "false", "no"}
    chat_ws_scheme = "wss" if request.is_secure() else "ws"
    chat_enabled = bool(getattr(settings, "WOWZA_LIVE_CHAT_ENABLED", True))
    context = {
        "app": app,
        "is_live": is_live,
        "hls_url": debug_hls_url if is_live or force_debug_player else "",
        "show_wowza_debug": show_wowza_debug,
        "force_debug_player": force_debug_player,
        "debug_hls_url": debug_hls_url,
        "debug_hls_path": parsed_hls_url.path,
        "debug_hls_params": parse_qsl(parsed_hls_url.query),
        "debug_hls_hash_algorithm": getattr(settings, "WOWZA_SECURE_TOKEN_HASH_ALGORITHM", "SHA-256"),
        "chat_enabled": chat_enabled,
        "chat_api_url": reverse("wowza_live_chat_messages", args=[app.name]) if chat_enabled else "",
        "chat_ws_url": f"{chat_ws_scheme}://{request.get_host()}/ws/live-chat/{app.id}/" if chat_enabled else "",
        "chat_can_write": chat_enabled and user_can_write_live_chat(request.user),
        "chat_can_moderate": chat_enabled and user_can_moderate_live_chat(request.user),
    }
    return render(request, "cms/wowza_live.html", context)



class LiveList(APIView):
    """Live listings views"""

    permission_classes = (IsAuthorizedToAdd,)
    parser_classes = (MultiPartParser, FormParser, FileUploadParser)

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name='page', type=openapi.TYPE_INTEGER, in_=openapi.IN_QUERY, description='Page number'),
            openapi.Parameter(name='author', type=openapi.TYPE_STRING, in_=openapi.IN_QUERY, description='username'),
            openapi.Parameter(name='show', type=openapi.TYPE_STRING, in_=openapi.IN_QUERY, description='show', enum=['recommended', 'featured', 'latest']),
        ],
        tags=['Live'],
        operation_summary='List Live',
        operation_description='Lists all lives',
        responses={200: MediaSerializer(many=True)},
    )
    def get(self, request, format=None):
        # Show media
        params = self.request.query_params
        show_param = params.get("show", "")
        folder_param = params.get("folder", "").strip()

        author_param = params.get("author", "").strip()
        if author_param:
            user_queryset = User.objects.all()
            user = get_object_or_404(user_queryset, username=author_param)
        if show_param == "recommended":
            pagination_class = FastPaginationWithoutCount
            media = show_recommended_media(request, limit=50)
        else:
            pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
            if author_param:
                # in case request.user is the user here, show
                # all media independant of state
                if self.request.user == user:
                    basic_query = Q(user=user)
                else:
                    basic_query = Q(listable=True, user=user)
            else:
                # base listings should show safe content
                basic_query = Q(listable=True)

            if folder_param == "live_record":
                media = Media.objects.filter(
                    basic_query,
                    media_file__contains="live_record/",
                ).order_by("-add_date")
            else:
                hls_filter = ~Q(stream="") & ~Q(stream__isnull=True)

                if show_param == "featured":
                    media = Media.objects.filter(basic_query & hls_filter, featured=True)
                else:
                    media = Media.objects.filter(basic_query & hls_filter).order_by("-add_date")

        paginator = pagination_class()

        if show_param != "recommended":
            media = media.prefetch_related("user")
        page = paginator.paginate_queryset(media, request)

        serializer = MediaSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

class MediaList(APIView):
    """Media listings views"""

    permission_classes = (IsAuthorizedToAdd,)
    parser_classes = (MultiPartParser, FormParser, FileUploadParser)

    def get_permissions(self):
        if getattr(settings, "GLOBAL_LOGIN_REQUIRED", False) and self.request.method in permissions.SAFE_METHODS:
            permission_classes = (permissions.IsAuthenticated,)
        else:
            permission_classes = self.permission_classes
        return [permission() for permission in permission_classes]

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name='page', type=openapi.TYPE_INTEGER, in_=openapi.IN_QUERY, description='Page number'),
            openapi.Parameter(name='author', type=openapi.TYPE_STRING, in_=openapi.IN_QUERY, description='username'),
            openapi.Parameter(name='show', type=openapi.TYPE_STRING, in_=openapi.IN_QUERY, description='show', enum=['recommended', 'featured', 'latest']),
        ],
        tags=['Media'],
        operation_summary='List Media',
        operation_description='Lists all media',
        responses={200: MediaSerializer(many=True)},
    )
    def get(self, request, format=None):
        # Show media
        params = self.request.query_params
        show_param = params.get("show", "")

        author_param = params.get("author", "").strip()
        if author_param:
            user_queryset = User.objects.all()
            user = get_object_or_404(user_queryset, username=author_param)
        if show_param == "recommended":
            pagination_class = FastPaginationWithoutCount
            media = show_recommended_media(request, limit=50)
        else:
            pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
            if author_param:
                # in case request.user is the user here, show
                # all media independant of state
                if self.request.user == user:
                    basic_query = Q(user=user)
                else:
                    basic_query = Q(listable=True, user=user)
            else:
                # base listings should show safe content
                basic_query = Q(listable=True)

            hls_filter = Q(stream="") | Q(stream__isnull=True)

            if show_param == "featured":
                media = Media.objects.filter(basic_query & hls_filter & Q(featured=True))
            else:
                media = Media.objects.filter(basic_query & hls_filter).order_by("-add_date")

        paginator = pagination_class()

        if show_param != "recommended":
            media = media.prefetch_related("user")
        page = paginator.paginate_queryset(media, request)

        serializer = MediaSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name="media_file", in_=openapi.IN_FORM, type=openapi.TYPE_FILE, required=True, description="media_file"),
            openapi.Parameter(name="description", in_=openapi.IN_FORM, type=openapi.TYPE_STRING, required=False, description="description"),
            openapi.Parameter(name="title", in_=openapi.IN_FORM, type=openapi.TYPE_STRING, required=False, description="title"),
        ],
        tags=['Media'],
        operation_summary='Add new Media',
        operation_description='Adds a new media, for authenticated users',
        responses={201: openapi.Response('response description', MediaSerializer), 401: 'bad request'},
    )
    def post(self, request, format=None):
        # Add new media
        serializer = MediaSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            media_file = request.data["media_file"]
            if not media_storage_has_capacity(getattr(media_file, "size", 0)):
                return Response({"detail": STORAGE_LIMIT_MESSAGE}, status=status.HTTP_403_FORBIDDEN)
            serializer.save(user=request.user, media_file=media_file)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MediaDetail(APIView):
    """
    Retrieve, update or delete a media instance.
    """

    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsUserOrEditor)
    parser_classes = (MultiPartParser, FormParser, FileUploadParser)

    def get_permissions(self):
        if getattr(settings, "GLOBAL_LOGIN_REQUIRED", False):
            permission_classes = (permissions.IsAuthenticated, IsUserOrEditor)
        else:
            permission_classes = self.permission_classes
        return [permission() for permission in permission_classes]

    def get_object(self, friendly_token, password=None):
        try:
            media = Media.objects.select_related("user").prefetch_related("encodings__profile").get(friendly_token=friendly_token)

            # this need be explicitly called, and will call
            # has_object_permission() after has_permission has succeeded
            self.check_object_permissions(self.request, media)

            if media.state == "private" and not (self.request.user == media.user or is_mediacms_editor(self.request.user)):
                if (not password) or (not media.password) or (password != media.password):
                    return Response(
                        {"detail": "media is private"},
                        status=status.HTTP_401_UNAUTHORIZED,
                    )
            return media
        except PermissionDenied:
            return Response({"detail": "bad permissions"}, status=status.HTTP_401_UNAUTHORIZED)
        except BaseException:
            return Response(
                {"detail": "media file does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name='friendly_token', type=openapi.TYPE_STRING, in_=openapi.IN_PATH, description='unique identifier', required=True),
        ],
        tags=['Media'],
        operation_summary='Get information for Media',
        operation_description='Get information for a media',
        responses={200: SingleMediaSerializer(), 400: 'bad request'},
    )
    def get(self, request, friendly_token, format=None):
        # Get media details
        if _user_requires_active_subscription_for_media_access(request.user) and not _user_has_media_access(request.user):
            data = {
                "detail": "No tienes una suscripcion activa.",
                "subscription_required": True,
                **_subscription_required_context(),
            }
            return Response(data, status=status.HTTP_403_FORBIDDEN)

        password = request.GET.get("password")
        media = self.get_object(friendly_token, password=password)
        if isinstance(media, Response):
            return media

        serializer = SingleMediaSerializer(media, context={"request": request})
        if media.state == "private":
            related_media = []
        else:
            related_media = show_related_media(media, request=request, limit=100)
            related_media_serializer = MediaSerializer(related_media, many=True, context={"request": request})
            related_media = related_media_serializer.data
        ret = serializer.data

        # update rattings info with user specific ratings
        # eg user has already rated for this media
        # this only affects user rating and only if enabled
        if settings.ALLOW_RATINGS and ret.get("ratings_info") and not request.user.is_anonymous:
            ret["ratings_info"] = update_user_ratings(request.user, media, ret.get("ratings_info"))

        ret["related_media"] = related_media
        return Response(ret)

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name='friendly_token', type=openapi.TYPE_STRING, in_=openapi.IN_PATH, description='unique identifier', required=True),
            openapi.Parameter(name='type', type=openapi.TYPE_STRING, in_=openapi.IN_FORM, description='action to perform', enum=['encode', 'review']),
            openapi.Parameter(
                name='encoding_profiles',
                type=openapi.TYPE_ARRAY,
                items=openapi.Items(type=openapi.TYPE_STRING),
                in_=openapi.IN_FORM,
                description='if action to perform is encode, need to specify list of ids of encoding profiles',
            ),
            openapi.Parameter(name='result', type=openapi.TYPE_BOOLEAN, in_=openapi.IN_FORM, description='if action is review, this is the result (True for reviewed, False for not reviewed)'),
        ],
        tags=['Media'],
        operation_summary='Run action on Media',
        operation_description='Actions for a media, for MediaCMS editors and managers',
        responses={201: 'action created', 400: 'bad request'},
        operation_id='media_manager_actions',
    )
    def post(self, request, friendly_token, format=None):
        """superuser actions
        Available only to MediaCMS editors and managers

        Action is a POST variable, review and encode are implemented
        """

        media = self.get_object(friendly_token)
        if isinstance(media, Response):
            return media

        if not (is_mediacms_editor(request.user) or is_mediacms_manager(request.user)):
            return Response({"detail": "not allowed"}, status=status.HTTP_400_BAD_REQUEST)

        action = request.data.get("type")
        profiles_list = request.data.get("encoding_profiles")
        result = request.data.get("result", True)
        if action == "encode":
            # Create encoding tasks for specific profiles
            valid_profiles = []
            if profiles_list:
                if isinstance(profiles_list, list):
                    for p in profiles_list:
                        p = EncodeProfile.objects.filter(id=p).first()
                        if p:
                            valid_profiles.append(p)
                elif isinstance(profiles_list, str):
                    try:
                        p = EncodeProfile.objects.filter(id=int(profiles_list)).first()
                        valid_profiles.append(p)
                    except ValueError:
                        return Response(
                            {"detail": "encoding_profiles must be int or list of ints of valid encode profiles"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
            media.encode(profiles=valid_profiles)
            return Response({"detail": "media will be encoded"}, status=status.HTTP_201_CREATED)
        elif action == "review":
            if result:
                media.is_reviewed = True
            elif result is False:
                media.is_reviewed = False
            media.save(update_fields=["is_reviewed"])
            return Response({"detail": "media reviewed set"}, status=status.HTTP_201_CREATED)
        return Response(
            {"detail": "not valid action or no action specified"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name="description", in_=openapi.IN_FORM, type=openapi.TYPE_STRING, required=False, description="description"),
            openapi.Parameter(name="title", in_=openapi.IN_FORM, type=openapi.TYPE_STRING, required=False, description="title"),
            openapi.Parameter(name="media_file", in_=openapi.IN_FORM, type=openapi.TYPE_FILE, required=False, description="media_file"),
        ],
        tags=['Media'],
        operation_summary='Update Media',
        operation_description='Update a Media, for Media uploader',
        responses={201: openapi.Response('response description', MediaSerializer), 401: 'bad request'},
    )
    def put(self, request, friendly_token, format=None):
        # Update a media object
        media = self.get_object(friendly_token)
        if isinstance(media, Response):
            return media
        serializer = MediaSerializer(media, data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save(user=request.user)
            # no need to update the media file itself, only the metadata
            # if request.data.get('media_file'):
            #    media_file = request.data["media_file"]
            #    serializer.save(user=request.user, media_file=media_file)
            # else:
            #    serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name='friendly_token', type=openapi.TYPE_STRING, in_=openapi.IN_PATH, description='unique identifier', required=True),
        ],
        tags=['Media'],
        operation_summary='Delete Media',
        operation_description='Delete a Media, for MediaCMS editors and managers',
        responses={
            204: 'no content',
        },
    )
    def delete(self, request, friendly_token, format=None):
        # Delete a media object
        media = self.get_object(friendly_token)
        if isinstance(media, Response):
            return media
        media.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MediaActions(APIView):
    """
    Retrieve, update or delete a media action instance.
    """

    permission_classes = (permissions.AllowAny,)
    parser_classes = (JSONParser,)

    def get_object(self, friendly_token):
        try:
            media = Media.objects.select_related("user").prefetch_related("encodings__profile").get(friendly_token=friendly_token)
            if media.state == "private" and self.request.user != media.user:
                return Response({"detail": "media is private"}, status=status.HTTP_400_BAD_REQUEST)
            return media
        except PermissionDenied:
            return Response({"detail": "bad permissions"}, status=status.HTTP_400_BAD_REQUEST)
        except BaseException:
            return Response(
                {"detail": "media file does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Media'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def get(self, request, friendly_token, format=None):
        # show date and reason for each time media was reported
        media = self.get_object(friendly_token)
        if not (request.user == media.user or is_mediacms_editor(request.user) or is_mediacms_manager(request.user)):
            return Response({"detail": "not allowed"}, status=status.HTTP_400_BAD_REQUEST)

        if isinstance(media, Response):
            return media

        ret = {}
        reported = MediaAction.objects.filter(media=media, action="report")
        ret["reported"] = []
        for rep in reported:
            item = {"reported_date": rep.action_date, "reason": rep.extra_info}
            ret["reported"].append(item)

        return Response(ret, status=status.HTTP_200_OK)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Media'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def post(self, request, friendly_token, format=None):
        # perform like/dislike/report actions
        media = self.get_object(friendly_token)
        if isinstance(media, Response):
            return media

        action = request.data.get("type")
        extra = request.data.get("extra_info")
        if request.user.is_anonymous:
            # there is a list of allowed actions for
            # anonymous users, specified in settings
            if action not in settings.ALLOW_ANONYMOUS_ACTIONS:
                return Response(
                    {"detail": "action allowed on logged in users only"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if action:
            user_or_session = get_user_or_session(request)
            save_user_action.delay(
                user_or_session,
                friendly_token=media.friendly_token,
                action=action,
                extra_info=extra,
            )

            return Response({"detail": "action received"}, status=status.HTTP_201_CREATED)
        else:
            return Response({"detail": "no action specified"}, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Media'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def delete(self, request, friendly_token, format=None):
        media = self.get_object(friendly_token)
        if isinstance(media, Response):
            return media

        if not request.user.is_superuser:
            return Response({"detail": "not allowed"}, status=status.HTTP_400_BAD_REQUEST)

        action = request.data.get("type")
        if action:
            if action == "report":  # delete reported actions
                MediaAction.objects.filter(media=media, action="report").delete()
                media.reported_times = 0
                media.save(update_fields=["reported_times"])
                return Response(
                    {"detail": "reset reported times counter"},
                    status=status.HTTP_201_CREATED,
                )
        else:
            return Response({"detail": "no action specified"}, status=status.HTTP_400_BAD_REQUEST)


class MediaSearch(APIView):
    """
    Retrieve results for searc
    Only GET is implemented here
    """

    parser_classes = (JSONParser,)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Search'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def get(self, request, format=None):
        params = self.request.query_params
        query = params.get("q", "").strip().lower()
        category = params.get("c", "").strip()
        tag = params.get("t", "").strip()

        ordering = params.get("ordering", "").strip()
        sort_by = params.get("sort_by", "").strip()
        media_type = params.get("media_type", "").strip()

        author = params.get("author", "").strip()
        upload_date = params.get('upload_date', '').strip()

        sort_by_options = ["title", "add_date", "edit_date", "views", "likes"]
        if sort_by not in sort_by_options:
            sort_by = "add_date"
        if ordering == "asc":
            ordering = ""
        else:
            ordering = "-"

        if media_type not in ["video", "image", "audio", "pdf"]:
            media_type = None

        if not (query or category or tag):
            ret = {}
            return Response(ret, status=status.HTTP_200_OK)

        media = Media.objects.filter(state="public", is_reviewed=True)

        if query:
            # move this processing to a prepare_query function
            query = clean_query(query)
            q_parts = [q_part.rstrip("y") for q_part in query.split() if q_part not in STOP_WORDS]
            if q_parts:
                query = SearchQuery(q_parts[0] + ":*", search_type="raw")
                for part in q_parts[1:]:
                    query &= SearchQuery(part + ":*", search_type="raw")
            else:
                query = None
        if query:
            media = media.filter(search=query)

        if tag:
            media = media.filter(tags__title=tag)

        if category:
            media = media.filter(category__title__contains=category)

        if media_type:
            media = media.filter(media_type=media_type)

        if author:
            media = media.filter(user__username=author)

        if upload_date:
            gte = None
            if upload_date == 'today':
                gte = datetime.now().date()
            if upload_date == 'this_week':
                gte = datetime.now() - timedelta(days=7)
            if upload_date == 'this_month':
                year = datetime.now().date().year
                month = datetime.now().date().month
                gte = datetime(year, month, 1)
            if upload_date == 'this_year':
                year = datetime.now().date().year
                gte = datetime(year, 1, 1)
            if gte:
                media = media.filter(add_date__gte=gte)

        media = media.order_by(f"{ordering}{sort_by}")

        if self.request.query_params.get("show", "").strip() == "titles":
            media = media.values("title")[:40]
            return Response(media, status=status.HTTP_200_OK)
        else:
            media = media.prefetch_related("user")
            if category or tag:
                pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
            else:
                # pagination_class = FastPaginationWithoutCount
                pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
            paginator = pagination_class()
            page = paginator.paginate_queryset(media, request)
            serializer = MediaSearchSerializer(page, many=True, context={"request": request})
            return paginator.get_paginated_response(serializer.data)


class PlaylistList(APIView):
    """Playlists listings and creation views"""

    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsAuthorizedToAdd)
    parser_classes = (JSONParser, MultiPartParser, FormParser, FileUploadParser)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Playlists'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
        responses={
            200: openapi.Response('response description', PlaylistSerializer(many=True)),
        },
    )
    def get(self, request, format=None):
        pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
        paginator = pagination_class()
        playlists = Playlist.objects.filter().prefetch_related("user")

        if "author" in self.request.query_params:
            author = self.request.query_params["author"].strip()
            playlists = playlists.filter(user__username=author)

        page = paginator.paginate_queryset(playlists, request)

        serializer = PlaylistSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Playlists'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def post(self, request, format=None):
        serializer = PlaylistSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PlaylistDetail(APIView):
    """Playlist related views"""

    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsUserOrEditor)
    parser_classes = (JSONParser, MultiPartParser, FormParser, FileUploadParser)

    def get_playlist(self, friendly_token):
        try:
            playlist = Playlist.objects.get(friendly_token=friendly_token)
            self.check_object_permissions(self.request, playlist)
            return playlist
        except PermissionDenied:
            return Response({"detail": "not enough permissions"}, status=status.HTTP_400_BAD_REQUEST)
        except BaseException:
            return Response(
                {"detail": "Playlist does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Playlists'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def get(self, request, friendly_token, format=None):
        playlist = self.get_playlist(friendly_token)
        if isinstance(playlist, Response):
            return playlist

        serializer = PlaylistDetailSerializer(playlist, context={"request": request})

        playlist_media = PlaylistMedia.objects.filter(playlist=playlist, media__state="public").prefetch_related("media__user")

        playlist_media = [c.media for c in playlist_media]

        playlist_media_serializer = MediaSerializer(playlist_media, many=True, context={"request": request})
        ret = serializer.data
        ret["playlist_media"] = playlist_media_serializer.data

        return Response(ret)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Playlists'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def post(self, request, friendly_token, format=None):
        playlist = self.get_playlist(friendly_token)
        if isinstance(playlist, Response):
            return playlist
        serializer = PlaylistDetailSerializer(playlist, data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Playlists'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def put(self, request, friendly_token, format=None):
        playlist = self.get_playlist(friendly_token)
        if isinstance(playlist, Response):
            return playlist
        action = request.data.get("type")
        media_friendly_token = request.data.get("media_friendly_token")
        ordering = 0
        if request.data.get("ordering"):
            try:
                ordering = int(request.data.get("ordering"))
            except ValueError:
                pass

        if action in ["add", "remove", "ordering"]:
            media = Media.objects.filter(friendly_token=media_friendly_token).first()
            if media:
                if action == "add":
                    media_in_playlist = PlaylistMedia.objects.filter(playlist=playlist).count()
                    if media_in_playlist >= settings.MAX_MEDIA_PER_PLAYLIST:
                        return Response(
                            {"detail": "max number of media for a Playlist reached"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    else:
                        obj, created = PlaylistMedia.objects.get_or_create(
                            playlist=playlist,
                            media=media,
                            ordering=media_in_playlist + 1,
                        )
                        obj.save()
                        return Response(
                            {"detail": "media added to Playlist"},
                            status=status.HTTP_201_CREATED,
                        )
                elif action == "remove":
                    PlaylistMedia.objects.filter(playlist=playlist, media=media).delete()
                    return Response(
                        {"detail": "media removed from Playlist"},
                        status=status.HTTP_201_CREATED,
                    )
                elif action == "ordering":
                    if ordering:
                        playlist.set_ordering(media, ordering)
                        return Response(
                            {"detail": "new ordering set"},
                            status=status.HTTP_201_CREATED,
                        )
            else:
                return Response({"detail": "media is not valid"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"detail": "invalid or not specified action"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Playlists'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def delete(self, request, friendly_token, format=None):
        playlist = self.get_playlist(friendly_token)
        if isinstance(playlist, Response):
            return playlist

        playlist.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EncodingDetail(APIView):
    """Experimental. This View is used by remote workers
    Needs heavy testing and documentation.
    """

    permission_classes = (permissions.IsAdminUser,)
    parser_classes = (JSONParser, MultiPartParser, FormParser, FileUploadParser)

    @swagger_auto_schema(auto_schema=None)
    def post(self, request, encoding_id):
        ret = {}
        force = request.data.get("force", False)
        task_id = request.data.get("task_id", False)
        action = request.data.get("action", "")
        chunk = request.data.get("chunk", False)
        chunk_file_path = request.data.get("chunk_file_path", "")

        encoding_status = request.data.get("status", "")
        progress = request.data.get("progress", "")
        commands = request.data.get("commands", "")
        logs = request.data.get("logs", "")
        retries = request.data.get("retries", "")
        worker = request.data.get("worker", "")
        temp_file = request.data.get("temp_file", "")
        total_run_time = request.data.get("total_run_time", "")
        if action == "start":
            try:
                encoding = Encoding.objects.get(id=encoding_id)
                media = encoding.media
                profile = encoding.profile
            except BaseException:
                Encoding.objects.filter(id=encoding_id).delete()
                return Response({"status": "fail"}, status=status.HTTP_400_BAD_REQUEST)
            # TODO: break chunk True/False logic here
            if (
                Encoding.objects.filter(
                    media=media,
                    profile=profile,
                    chunk=chunk,
                    chunk_file_path=chunk_file_path,
                ).count()
                > 1  # noqa
                and force is False  # noqa
            ):
                Encoding.objects.filter(id=encoding_id).delete()
                return Response({"status": "fail"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                Encoding.objects.filter(
                    media=media,
                    profile=profile,
                    chunk=chunk,
                    chunk_file_path=chunk_file_path,
                ).exclude(id=encoding.id).delete()

            encoding.status = "running"
            if task_id:
                encoding.task_id = task_id

            encoding.save()
            if chunk:
                original_media_path = chunk_file_path
                original_media_md5sum = encoding.md5sum
                original_media_url = settings.SSL_FRONTEND_HOST + encoding.media_chunk_url
            else:
                original_media_path = media.media_file.path
                original_media_md5sum = media.md5sum
                original_media_url = settings.SSL_FRONTEND_HOST + media.original_media_url

            ret["original_media_url"] = original_media_url
            ret["original_media_path"] = original_media_path
            ret["original_media_md5sum"] = original_media_md5sum

            # generating the commands here, and will replace these with temporary
            # files created on the remote server
            tf = "TEMP_FILE_REPLACE"
            tfpass = "TEMP_FPASS_FILE_REPLACE"
            ffmpeg_commands = produce_ffmpeg_commands(
                original_media_path,
                media.media_info,
                resolution=profile.resolution,
                codec=profile.codec,
                output_filename=tf,
                pass_file=tfpass,
                chunk=chunk,
            )
            if not ffmpeg_commands:
                encoding.delete()
                return Response({"status": "fail"}, status=status.HTTP_400_BAD_REQUEST)

            ret["duration"] = media.duration
            ret["ffmpeg_commands"] = ffmpeg_commands
            ret["profile_extension"] = profile.extension
            return Response(ret, status=status.HTTP_201_CREATED)
        elif action == "update_fields":
            try:
                encoding = Encoding.objects.get(id=encoding_id)
            except BaseException:
                return Response({"status": "fail"}, status=status.HTTP_400_BAD_REQUEST)
            to_update = ["size", "update_date"]
            if encoding_status:
                encoding.status = encoding_status
                to_update.append("status")
            if progress:
                encoding.progress = progress
                to_update.append("progress")
            if logs:
                encoding.logs = logs
                to_update.append("logs")
            if commands:
                encoding.commands = commands
                to_update.append("commands")
            if task_id:
                encoding.task_id = task_id
                to_update.append("task_id")
            if total_run_time:
                encoding.total_run_time = total_run_time
                to_update.append("total_run_time")
            if worker:
                encoding.worker = worker
                to_update.append("worker")
            if temp_file:
                encoding.temp_file = temp_file
                to_update.append("temp_file")

            if retries:
                encoding.retries = retries
                to_update.append("retries")

            try:
                encoding.save(update_fields=to_update)
            except BaseException:
                return Response({"status": "fail"}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"status": "success"}, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(auto_schema=None)
    def put(self, request, encoding_id, format=None):
        encoding_file = request.data["file"]
        encoding = Encoding.objects.filter(id=encoding_id).first()
        if not encoding:
            return Response(
                {"detail": "encoding does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        encoding.media_file = encoding_file
        encoding.save()
        return Response({"detail": "ok"}, status=status.HTTP_201_CREATED)


class CommentList(APIView):
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsAuthorizedToAdd)
    parser_classes = (JSONParser, MultiPartParser, FormParser, FileUploadParser)

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name='page', type=openapi.TYPE_INTEGER, in_=openapi.IN_QUERY, description='Page number'),
            openapi.Parameter(name='author', type=openapi.TYPE_STRING, in_=openapi.IN_QUERY, description='username'),
        ],
        tags=['Comments'],
        operation_summary='Lists Comments',
        operation_description='Paginated listing of all comments',
        responses={
            200: openapi.Response('response description', CommentSerializer(many=True)),
        },
    )
    def get(self, request, format=None):
        pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
        paginator = pagination_class()
        comments = Comment.objects.filter(media__state="public").order_by("-add_date")
        comments = comments.prefetch_related("user")
        comments = comments.prefetch_related("media")
        params = self.request.query_params
        if "author" in params:
            author_param = params["author"].strip()
            user_queryset = User.objects.all()
            user = get_object_or_404(user_queryset, username=author_param)
            comments = comments.filter(user=user)

        page = paginator.paginate_queryset(comments, request)

        serializer = CommentSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)


class CommentDetail(APIView):
    """Comments related views
    Listings of comments for a media (GET)
    Create comment (POST)
    Delete comment (DELETE)
    """

    permission_classes = (IsAuthorizedToAddComment,)
    parser_classes = (JSONParser, MultiPartParser, FormParser, FileUploadParser)

    def get_object(self, friendly_token):
        try:
            media = Media.objects.select_related("user").get(friendly_token=friendly_token)
            self.check_object_permissions(self.request, media)
            if media.state == "private" and self.request.user != media.user:
                return Response({"detail": "media is private"}, status=status.HTTP_400_BAD_REQUEST)
            return media
        except PermissionDenied:
            return Response({"detail": "bad permissions"}, status=status.HTTP_400_BAD_REQUEST)
        except BaseException:
            return Response(
                {"detail": "media file does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Media'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def get(self, request, friendly_token):
        # list comments for a media
        media = self.get_object(friendly_token)
        if isinstance(media, Response):
            return media
        comments = media.comments.filter().prefetch_related("user")
        pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
        paginator = pagination_class()
        page = paginator.paginate_queryset(comments, request)
        serializer = CommentSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Media'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def delete(self, request, friendly_token, uid=None):
        """Delete a comment
        Administrators, MediaCMS editors and managers,
        media owner, and comment owners, can delete a comment
        """
        if uid:
            try:
                comment = Comment.objects.get(uid=uid)
            except BaseException:
                return Response(
                    {"detail": "comment does not exist"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if (comment.user == self.request.user) or comment.media.user == self.request.user or is_mediacms_editor(self.request.user):
                comment.delete()
            else:
                return Response({"detail": "bad permissions"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Media'],
        operation_summary='to_be_written',
        operation_description='to_be_written',
    )
    def post(self, request, friendly_token):
        """Create a comment"""
        media = self.get_object(friendly_token)
        if isinstance(media, Response):
            return media

        if not media.enable_comments:
            return Response(
                {"detail": "comments not allowed here"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CommentSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save(user=request.user, media=media)
            if request.user != media.user:
                notify_user_on_comment(friendly_token=media.friendly_token)
            # here forward the comment to check if a user was mentioned
            if settings.ALLOW_MENTION_IN_COMMENTS:
                check_comment_for_mention(friendly_token=media.friendly_token, comment_text=serializer.data['text'])
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserActions(APIView):
    parser_classes = (JSONParser,)

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name='action', type=openapi.TYPE_STRING, in_=openapi.IN_PATH, description='action', required=True, enum=VALID_USER_ACTIONS),
        ],
        tags=['Users'],
        operation_summary='List user actions',
        operation_description='Lists user actions',
    )
    def get(self, request, action):
        media = []
        if action in VALID_USER_ACTIONS:
            if request.user.is_authenticated:
                media = Media.objects.select_related("user").filter(mediaactions__user=request.user, mediaactions__action=action).order_by("-mediaactions__action_date")
            elif request.session.session_key:
                media = (
                    Media.objects.select_related("user")
                    .filter(
                        mediaactions__session_key=request.session.session_key,
                        mediaactions__action=action,
                    )
                    .order_by("-mediaactions__action_date")
                )

        pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
        paginator = pagination_class()
        page = paginator.paginate_queryset(media, request)
        serializer = MediaSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)


class CategoryList(APIView):
    """List categories"""

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Categories'],
        operation_summary='Lists Categories',
        operation_description='Lists all categories',
        responses={
            200: openapi.Response('response description', CategorySerializer),
        },
    )
    def get(self, request, format=None):
        categories = Category.objects.filter().order_by("title")
        serializer = CategorySerializer(categories, many=True, context={"request": request})
        ret = serializer.data
        return Response(ret)

class AdsList(APIView):
    """List Ads"""

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name='page', type=openapi.TYPE_INTEGER, in_=openapi.IN_QUERY, description='Page number'),
        ],
        tags=['Ads'],
        operation_summary='Lists Ads',
        operation_description='Lists all ads',
        responses={
            200: openapi.Response('response description', AdsSerializer),
        },
    )
    def get(self, request, format=None):
        ads = Ads.objects.filter().order_by("name")
        serializer = AdsSerializer(ads, many=True, context={"request": request})
        pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
        paginator = pagination_class()
        page = paginator.paginate_queryset(ads, request)
        return paginator.get_paginated_response(serializer.data)

    def delete(self, request, format=None):
        tokens = request.query_params.get("tokens")
        if not tokens:
            return Response({"error": "No tokens provided"}, status=status.HTTP_400_BAD_REQUEST)

        token_ids = [int(t.strip()) for t in tokens.split(",") if t.strip().isdigit()]
        deleted_count, _ = Ads.objects.filter(id__in=token_ids).delete()

        return Response(
            {"message": f"{deleted_count} ad(s) deleted."},
            status=status.HTTP_204_NO_CONTENT
        )

class CategoryAdsList(APIView):
    """List Category Ads"""

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Categories'],
        operation_summary='Lists Categories',
        operation_description='Lists all categories',
        responses={
            200: openapi.Response('response description', CategorySerializer),
        },
    )

    def get(self, request, format=None):
        categories = Category.objects.filter().order_by("title")
        serializer = CategorySerializer(categories, many=True, context={"request": request})
        pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
        paginator = pagination_class()
        page = paginator.paginate_queryset(categories, request)
        return paginator.get_paginated_response(serializer.data)


class AssignAdToAllMedia(APIView):
    @swagger_auto_schema(
        operation_summary="Assign Ad to ALL Media",
        operation_description="Assigns the selected Ad to ALL Media in the system.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['ad_id'],
            properties={
                'ad_id': openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    description='ID of the Ad to assign',
                ),
            },
        ),
        responses={
            200: openapi.Response(description="Ad assigned to all media"),
            400: openapi.Response(description="Invalid input or ad not found"),
        }
    )
    def post(self, request, *args, **kwargs):
        ad_id = request.data.get("ad_id")
        if not ad_id:
            return Response({"detail": "Missing ad_id"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ad = Ads.objects.get(id=ad_id)
        except Ads.DoesNotExist:
            return Response({"detail": "Ad not found"}, status=status.HTTP_400_BAD_REQUEST)

        updated_count = Media.objects.update(ad_tag=ad)
        return Response({"message": f"Ad assigned to {updated_count} media items."}, status=status.HTTP_200_OK)


class AssignAdToMediaByCategory(APIView):
    @swagger_auto_schema(
        operation_summary="Assign Ad to all Media in selected Categories",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['category_ids', 'ad_id'],
            properties={
                'category_ids': openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description='IDs of categories selected'
                ),
                'ad_id': openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    description='Ad ID to assign'
                ),
            }
        ),
        responses={
            200: openapi.Response(description="Ad assigned successfully"),
            400: openapi.Response(description="Invalid input"),
        }
    )
    def post(self, request, *args, **kwargs):
        category_ids = request.data.get("category_ids")
        ad_id = request.data.get("ad_id")

        if not category_ids or not ad_id:
            return Response({"detail": "Missing category_ids or ad_id"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ad = Ads.objects.get(id=ad_id)
        except Ads.DoesNotExist:
            return Response({"detail": "Ad not found"}, status=status.HTTP_400_BAD_REQUEST)

        updated_count = Media.objects.filter(category__id__in=category_ids).update(ad_tag=ad)
        return Response({"message": f"Ad assigned to {updated_count} media items."}, status=status.HTTP_200_OK)


class TagList(APIView):
    """List tags"""

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(name='page', type=openapi.TYPE_INTEGER, in_=openapi.IN_QUERY, description='Page number'),
        ],
        tags=['Tags'],
        operation_summary='Lists Tags',
        operation_description='Paginated listing of all tags',
        responses={
            200: openapi.Response('response description', TagSerializer),
        },
    )
    def get(self, request, format=None):
        tags = Tag.objects.filter().order_by("-media_count")
        pagination_class = api_settings.DEFAULT_PAGINATION_CLASS
        paginator = pagination_class()
        page = paginator.paginate_queryset(tags, request)
        serializer = TagSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)


class EncodeProfileList(APIView):
    """List encode profiles"""

    @swagger_auto_schema(
        manual_parameters=[],
        tags=['Encoding Profiles'],
        operation_summary='List Encoding Profiles',
        operation_description='Lists all encoding profiles for videos',
        responses={200: EncodeProfileSerializer(many=True)},
    )
    def get(self, request, format=None):
        profiles = EncodeProfile.objects.all()
        serializer = EncodeProfileSerializer(profiles, many=True, context={"request": request})
        return Response(serializer.data)


class TasksList(APIView):
    """List tasks"""

    swagger_schema = None

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request, format=None):
        ret = list_tasks()
        return Response(ret)


class TaskDetail(APIView):
    """Cancel a task"""

    swagger_schema = None

    permission_classes = (permissions.IsAdminUser,)

    def delete(self, request, uid, format=None):
        # This is not imported!
        # revoke(uid, terminate=True)
        return Response(status=status.HTTP_204_NO_CONTENT)
