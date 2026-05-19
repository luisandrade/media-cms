# Kudos to Werner Robitza, AVEQ GmbH, for helping with ffmpeg
# related content

import itertools
import logging
import os
import random
import re
from datetime import datetime

from django.conf import settings
from django.core.files import File
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.db.models import Q
from django.utils import timezone

from cms import celery_app

from . import models
from .helpers import get_file_type, mask_ip

logger = logging.getLogger(__name__)


def _requeue_live_record_media(media):
    if media.media_type != "video":
        return False

    has_real_encodings = media.encodings.exclude(profile__extension="gif").filter(chunk=False).exists()
    if has_real_encodings:
        return False

    media.set_media_type(save=False)
    if settings.DO_NOT_TRANSCODE_VIDEO:
        media.encoding_status = "success"
    else:
        media.encoding_status = "pending"

    media.listable = False
    media.save(
        update_fields=[
            "listable",
            "media_type",
            "duration",
            "media_info",
            "video_height",
            "size",
            "md5sum",
            "encoding_status",
        ]
    )

    if settings.DO_NOT_TRANSCODE_VIDEO:
        media.produce_sprite_from_video()
    else:
        media.produce_sprite_from_video()
        media.encode(force=False)

    return True


def _update_live_record_media(media, publish=False, reviewed=True):
    media.is_reviewed = reviewed
    if publish:
        media.state = "public"

    media.listable = media.state == "public" and media.encoding_status == "success" and media.is_reviewed is True
    media.save(update_fields=["state", "is_reviewed", "listable"])

    _requeue_live_record_media(media)


def sync_live_record_media(user, folder=None, publish=False, reviewed=True):
    """Create Media rows for files already present inside live_record.

    Files are registered in-place, keeping their path relative to MEDIA_ROOT,
    so the recorded section can target that folder directly.
    """

    folder = folder or os.path.join(settings.MEDIA_ROOT, "live_record")
    folder = os.path.realpath(folder)
    media_root = os.path.realpath(settings.MEDIA_ROOT)

    if not folder.startswith(media_root):
        raise ValueError("Folder must be inside MEDIA_ROOT")

    result = {
        "created": [],
        "updated": [],
        "skipped": [],
    }

    if not os.path.isdir(folder):
        return result

    channel = user.channels.order_by("add_date").first()

    for dirpath, _, filenames in os.walk(folder):
        for filename in sorted(filenames):
            absolute_path = os.path.join(dirpath, filename)

            if not os.path.isfile(absolute_path):
                continue

            media_kind = get_file_type(absolute_path)
            if media_kind not in {"video", "audio", "image", "pdf"}:
                result["skipped"].append({
                    "path": absolute_path,
                    "reason": "unsupported",
                })
                continue

            relative_path = os.path.relpath(absolute_path, settings.MEDIA_ROOT).replace(os.sep, "/")

            existing_media = models.Media.objects.filter(media_file=relative_path).first()
            if existing_media:
                _update_live_record_media(existing_media, publish=publish, reviewed=reviewed)
                result["updated"].append(existing_media)
                result["skipped"].append({
                    "path": relative_path,
                    "reason": "already_registered",
                })
                continue

            modified_at = datetime.fromtimestamp(
                os.path.getmtime(absolute_path),
                tz=timezone.get_current_timezone(),
            )

            media = models.Media(
                user=user,
                channel=channel,
                media_file=relative_path,
                title=os.path.splitext(filename)[0][:99],
                add_date=modified_at,
                is_reviewed=reviewed,
            )

            if publish:
                media.state = "public"

            media.save()
            _update_live_record_media(media, publish=publish, reviewed=reviewed)
            result["created"].append(media)

    return result


def get_user_or_session(request):
    """Return a dictionary with user info
    whether user is authenticated or not
    this is used in action calculations, example for
    increasing the watch counter of a media
    """

    ret = {}
    if request.user.is_authenticated:
        ret["user_id"] = request.user.id
    else:
        if not request.session.session_key:
            request.session.save()
        ret["user_session"] = request.session.session_key
    if settings.MASK_IPS_FOR_ACTIONS:
        ret["remote_ip_addr"] = mask_ip(request.META.get("REMOTE_ADDR"))
    else:
        ret["remote_ip_addr"] = request.META.get("REMOTE_ADDR")
    return ret


def pre_save_action(media, user, session_key, action, remote_ip):
    """This will perform some checkes
    example threshold checks, before performing an action
    """

    from actions.models import MediaAction

    if user:
        query = MediaAction.objects.filter(media=media, action=action, user=user)
    else:
        query = MediaAction.objects.filter(media=media, action=action, session_key=session_key)
    query = query.order_by("-action_date")

    if query:
        query = query.first()
        if action in ["like", "dislike", "report"]:
            return False  # has alread done action once
        elif action == "watch" and user:
            # increase the number of times a media is viewed
            if media.duration:
                now = datetime.now(query.action_date.tzinfo)
                if (now - query.action_date).seconds > media.duration:
                    return True
    else:
        if user:  # first time action
            return True

    if not user:
        # perform some checking for requests where no session
        # id is specified (and user is anonymous) to avoid spam
        # eg allow for the same remote_ip for a specific number of actions
        query = MediaAction.objects.filter(media=media, action=action, remote_ip=remote_ip).filter(user=None).order_by("-action_date")
        if query:
            query = query.first()
            now = datetime.now(query.action_date.tzinfo)
            if action == "watch":
                if not (now - query.action_date).seconds > media.duration:
                    return False
            if (now - query.action_date).seconds > settings.TIME_TO_ACTION_ANONYMOUS:
                return True
        else:
            return True

    return False


def is_mediacms_editor(user):
    """Whether user is MediaCMS editor"""

    editor = False
    try:
        if user.is_superuser or user.is_manager or user.is_editor:
            editor = True
    except BaseException:
        pass
    return editor


def is_mediacms_manager(user):
    """Whether user is MediaCMS manager"""

    manager = False
    try:
        if user.is_superuser or user.is_manager:
            manager = True
    except BaseException:
        pass
    return manager


def get_next_state(user, current_state, next_state):
    """Return valid state, given a current and next state
    and the user object.
    Users may themselves perform only allowed transitions
    """

    if next_state not in ["public", "private", "unlisted"]:
        next_state = settings.PORTAL_WORKFLOW  # get default state

    if is_mediacms_editor(user):
        # allow any transition
        return next_state

    if settings.PORTAL_WORKFLOW == "private":
        if next_state in ["private", "unlisted"]:
            next_state = next_state
        else:
            next_state = current_state

    if settings.PORTAL_WORKFLOW == "unlisted":
        # don't allow to make media public in this case
        if next_state == "public":
            next_state = current_state

    return next_state


def notify_users(friendly_token=None, action=None, extra=None):
    """Notify users through email, for a set of actions"""

    notify_items = []
    media = None
    if friendly_token:
        media = models.Media.objects.filter(friendly_token=friendly_token).first()
        if not media:
            return False
        media_url = settings.SSL_FRONTEND_HOST + media.get_absolute_url()

    if action == "media_reported" and media:
        msg = """
El contenido %s fue reportado.
Motivo: %s\n
Total de veces que este contenido ha sido reportado: %s\n
El contenido pasa a privado si se reporta %s veces\n
        """ % (
            media_url,
            extra,
            media.reported_times,
            settings.REPORTED_TIMES_THRESHOLD,
        )

        if settings.ADMINS_NOTIFICATIONS.get("MEDIA_REPORTED", False):
            title = "[{}] - Contenido reportado".format(settings.PORTAL_NAME)
            d = {}
            d["title"] = title
            d["msg"] = msg
            d["to"] = settings.ADMIN_EMAIL_LIST
            notify_items.append(d)
        if settings.USERS_NOTIFICATIONS.get("MEDIA_REPORTED", False):
            title = "[{}] - Contenido reportado".format(settings.PORTAL_NAME)
            d = {}
            d["title"] = title
            d["msg"] = msg
            d["to"] = [media.user.email]
            notify_items.append(d)

    if action == "media_added" and media:
        if settings.ADMINS_NOTIFICATIONS.get("MEDIA_ADDED", False):
            title = "[{}] - Contenido agregado".format(settings.PORTAL_NAME)
            msg = """
El contenido %s fue agregado por el usuario %s.
""" % (
                media_url,
                media.user,
            )
            d = {}
            d["title"] = title
            d["msg"] = msg
            d["to"] = settings.ADMIN_EMAIL_LIST
            notify_items.append(d)
        if settings.USERS_NOTIFICATIONS.get("MEDIA_ADDED", False):
            title = "[{}] - Tu contenido fue agregado".format(settings.PORTAL_NAME)
            msg = """
¡Tu contenido fue agregado! Se codificará y estará disponible pronto.
URL: %s
            """ % (
                media_url
            )
            d = {}
            d["title"] = title
            d["msg"] = msg
            d["to"] = [media.user.email]
            notify_items.append(d)

    for item in notify_items:
        email = EmailMessage(item["title"], item["msg"], settings.DEFAULT_FROM_EMAIL, item["to"])
        email.send(fail_silently=True)
    return True


def copy_video(original_media, copy_encodings=True, title_suffix="(Trimmed)"):
    """Create a copy of a video media item and optionally its successful encodings."""

    with open(original_media.media_file.path, "rb") as file_handle:
        media_file = File(file_handle)
        new_media = models.Media(
            media_file=media_file,
            title=f"{original_media.title} {title_suffix}",
            description=original_media.description,
            user=original_media.user,
            media_type="video",
            enable_comments=original_media.enable_comments,
            allow_download=original_media.allow_download,
            state=original_media.state,
            is_reviewed=original_media.is_reviewed,
            encoding_status=original_media.encoding_status,
            listable=original_media.listable,
            add_date=timezone.now(),
            video_height=original_media.video_height,
            media_info=original_media.media_info,
        )
        models.Media.objects.bulk_create([new_media])

    if copy_encodings:
        for encoding in original_media.encodings.filter(chunk=False, status="success"):
            if encoding.media_file:
                with open(encoding.media_file.path, "rb") as file_handle:
                    media_file = File(file_handle)
                    new_encoding = models.Encoding(
                        media_file=media_file,
                        media=new_media,
                        profile=encoding.profile,
                        status="success",
                        progress=100,
                        chunk=False,
                        logs=f"Copied from encoding {encoding.id}",
                    )
                    models.Encoding.objects.bulk_create([new_encoding])

    for category in original_media.category.all():
        new_media.category.add(category)

    for tag in original_media.tags.all():
        new_media.tags.add(tag)

    if original_media.thumbnail:
        with open(original_media.thumbnail.path, "rb") as file_handle:
            thumbnail_name = original_media.thumbnail.name.split("/")[-1]
            new_media.thumbnail.save(thumbnail_name, File(file_handle))

    if original_media.poster:
        with open(original_media.poster.path, "rb") as file_handle:
            poster_name = original_media.poster.name.split("/")[-1]
            new_media.poster.save(poster_name, File(file_handle))

    return new_media


def create_video_trim_request(media, data):
    """Create a trim request from the editor payload."""

    video_action = "replace"
    if data.get("saveIndividualSegments"):
        video_action = "create_segments"
    elif data.get("saveAsCopy"):
        video_action = "save_new"

    return models.VideoTrimRequest.objects.create(
        media=media,
        status="initial",
        video_action=video_action,
        media_trim_style="no_encoding",
        timestamps=data.get("segments", {}),
    )


def show_recommended_media(request, limit=100):
    """Return a list of recommended media
    used on the index page
    """

    basic_query = Q(listable=True)
    pmi = cache.get("popular_media_ids")
    # produced by task get_list_of_popular_media and cached
    if pmi:
        media = list(models.Media.objects.filter(friendly_token__in=pmi).filter(basic_query).prefetch_related("user")[:limit])
    else:
        media = list(models.Media.objects.filter(basic_query).order_by("-views", "-likes").prefetch_related("user")[:limit])
    random.shuffle(media)
    return media


def show_related_media(media, request=None, limit=100):
    """Return a list of related media"""

    if settings.RELATED_MEDIA_STRATEGY == "calculated":
        return show_related_media_calculated(media, request, limit)
    elif settings.RELATED_MEDIA_STRATEGY == "author":
        return show_related_media_author(media, request, limit)

    return show_related_media_content(media, request, limit)


def show_related_media_content(media, request, limit):
    """Return a list of related media based on simple calculations"""

    # Create list with author items
    # then items on same category, then some random(latest)
    # Aim is to always show enough (limit) videos
    # and include author videos in any case

    q_author = Q(listable=True, user=media.user)
    m = list(models.Media.objects.filter(q_author).order_by().prefetch_related("user")[:limit])

    # order by random criteria so that it doesn't bring the same results
    # attention: only fields that are indexed make sense here! also need
    # find a way for indexes with more than 1 field
    order_criteria = [
        "-views",
        "views",
        "add_date",
        "-add_date",
        "featured",
        "-featured",
        "user_featured",
        "-user_featured",
    ]
    # TODO: MAke this mess more readable, and add TAGS support - aka related
    # tags rather than random media
    if len(m) < limit:
        category = media.category.first()
        if category:
            q_category = Q(listable=True, category=category)
            q_res = models.Media.objects.filter(q_category).order_by(order_criteria[random.randint(0, len(order_criteria) - 1)]).prefetch_related("user")[: limit - media.user.media_count]
            m = list(itertools.chain(m, q_res))

        if len(m) < limit:
            q_generic = Q(listable=True)
            q_res = models.Media.objects.filter(q_generic).order_by(order_criteria[random.randint(0, len(order_criteria) - 1)]).prefetch_related("user")[: limit - media.user.media_count]
            m = list(itertools.chain(m, q_res))

    m = list(set(m[:limit]))  # remove duplicates

    try:
        m.remove(media)  # remove media from results
    except ValueError:
        pass

    random.shuffle(m)
    return m


def show_related_media_author(media, request, limit):
    """Return a list of related media form the same author"""

    q_author = Q(listable=True, user=media.user)
    m = list(models.Media.objects.filter(q_author).order_by().prefetch_related("user")[:limit])

    # order by random criteria so that it doesn't bring the same results
    # attention: only fields that are indexed make sense here! also need
    # find a way for indexes with more than 1 field

    m = list(set(m[:limit]))  # remove duplicates

    try:
        m.remove(media)  # remove media from results
    except ValueError:
        pass

    random.shuffle(m)
    return m


def show_related_media_calculated(media, request, limit):
    """Return a list of related media based on ML recommendations
    A big todo!
    """

    return []


def update_user_ratings(user, media, user_ratings):
    """Populate user ratings for a media"""

    for rating in user_ratings:
        user_rating = models.Rating.objects.filter(user=user, media_id=media, rating_category_id=rating.get("category_id")).only("score").first()
        if user_rating:
            rating["score"] = user_rating.score
    return user_ratings


def notify_user_on_comment(friendly_token):
    """Notify users through email, for a set of actions"""
    media = models.Media.objects.filter(friendly_token=friendly_token).first()
    if not media:
        return False

    user = media.user
    media_url = settings.SSL_FRONTEND_HOST + media.get_absolute_url()

    if user.notification_on_comments:
        title = "[{}] - Se agregó un comentario".format(settings.PORTAL_NAME)
        msg = """
Se agregó un comentario a tu contenido %s.
Revísalo en %s
        """ % (
            media.title,
            media_url,
        )
        email = EmailMessage(title, msg, settings.DEFAULT_FROM_EMAIL, [media.user.email])
        email.send(fail_silently=True)
    return True


def notify_user_on_mention(friendly_token, user_mentioned, cleaned_comment):
    from users.models import User

    media = models.Media.objects.filter(friendly_token=friendly_token).first()
    if not media:
        return False

    user = User.objects.filter(username=user_mentioned).first()
    media_url = settings.SSL_FRONTEND_HOST + media.get_absolute_url()

    if user.notification_on_comments:
        title = "[{}] - Te mencionaron en un comentario".format(settings.PORTAL_NAME)
        msg = """
Te mencionaron en un comentario en %s.
Revísalo en %s

Comentario: %s
        """ % (
            media.title,
            media_url,
            cleaned_comment,
        )
        email = EmailMessage(title, msg, settings.DEFAULT_FROM_EMAIL, [user.email])
        email.send(fail_silently=True)
    return True


def check_comment_for_mention(friendly_token, comment_text):
    """Check the comment for any mentions, and notify each mentioned users"""
    cleaned_comment = ''

    matches = re.findall('@\\(_(.+?)_\\)', comment_text)
    if matches:
        cleaned_comment = clean_comment(comment_text)

    for match in list(dict.fromkeys(matches)):
        notify_user_on_mention(friendly_token, match, cleaned_comment)


def clean_comment(raw_comment):
    """Clean the comment fromn ID and username Mentions for preview purposes"""

    cleaned_comment = re.sub('@\\(_(.+?)_\\)', '', raw_comment)
    cleaned_comment = cleaned_comment.replace("[_", '')
    cleaned_comment = cleaned_comment.replace("_]", '')

    return cleaned_comment


def list_tasks():
    """Lists celery tasks
    To be used in an admin dashboard
    """

    i = celery_app.control.inspect([])
    ret = {}
    temp = {}
    task_ids = []
    media_profile_pairs = []

    temp["active"] = i.active()
    temp["reserved"] = i.reserved()
    temp["scheduled"] = i.scheduled()

    for state, state_dict in temp.items():
        ret[state] = {}
        ret[state]["tasks"] = []
        for worker, worker_dict in state_dict.items():
            for task in worker_dict:
                task_dict = {}
                task_dict["worker"] = worker
                task_dict["task_id"] = task.get("id")
                task_ids.append(task.get("id"))
                task_dict["args"] = task.get("args")
                task_dict["name"] = task.get("name")
                task_dict["time_start"] = task.get("time_start")
                if task.get("name") == "encode_media":
                    task_args = task.get("args")
                    for bad in "(),'":
                        task_args = task_args.replace(bad, "")
                    friendly_token = task_args.split()[0]
                    profile_id = task_args.split()[1]

                    media = models.Media.objects.filter(friendly_token=friendly_token).first()
                    if media:
                        profile = models.EncodeProfile.objects.filter(id=profile_id).first()
                        if profile:
                            media_profile_pairs.append((media.friendly_token, profile.id))
                            task_dict["info"] = {}
                            task_dict["info"]["profile name"] = profile.name
                            task_dict["info"]["media title"] = media.title
                            encoding = models.Encoding.objects.filter(task_id=task.get("id")).first()
                            if encoding:
                                task_dict["info"]["encoding progress"] = encoding.progress

                ret[state]["tasks"].append(task_dict)
    ret["task_ids"] = task_ids
    ret["media_profile_pairs"] = media_profile_pairs
    return ret
