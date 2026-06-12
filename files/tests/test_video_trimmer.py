from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from files.models import EncodeProfile, Encoding, Media, VideoTrimRequest
from files.tasks import post_trim_action
from files.tests.user_utils import create_account


class VideoTrimmerTests(TestCase):
    @patch("files.models.Media.media_init", return_value=True)
    def setUp(self, media_init):
        self.user = create_account(username="trimadmin", password="pass1234", email="trimadmin@example.com")
        self.media = Media.objects.create(
            user=self.user,
            title="Video para recortar",
            media_file=SimpleUploadedFile("video.mp4", b"fake video", content_type="video/mp4"),
            media_type="video",
            encoding_status="success",
            video_height=720,
        )
        self.profile = EncodeProfile.objects.create(name="720p h264", extension="mp4", resolution=720, codec="h264")
        self.encoding = Encoding.objects.create(media=self.media, profile=self.profile, status="pending")
        Encoding.objects.filter(id=self.encoding.id).update(status="success")
        VideoTrimRequest.objects.create(
            media=self.media,
            status="running",
            video_action="replace",
            media_trim_style="no_encoding",
            timestamps=[{"startTime": "00:00:00.000", "endTime": "00:00:02.000"}],
        )

    @patch("files.tasks.create_hls.delay")
    @patch("files.tasks.produce_sprite_from_video.delay")
    @patch("files.models.Media.produce_thumbnails_from_video", return_value=True)
    @patch("files.models.Media.set_media_type", return_value=True)
    @patch("files.models.generate_smil", return_value="/tmp/video.smil")
    def test_post_trim_action_regenerates_smil_for_trimmed_video(
        self,
        generate_smil,
        set_media_type,
        produce_thumbnails_from_video,
        produce_sprite_from_video_delay,
        create_hls_delay,
    ):
        result = post_trim_action(self.media.friendly_token)

        self.assertEqual(result, True)
        generate_smil.assert_called_once()
        self.assertEqual(generate_smil.call_args[0][0].id, self.media.id)
        self.media.refresh_from_db()
        self.assertEqual(self.media.encoding_status, "waiting_smil")
        trim_request = VideoTrimRequest.objects.get(media=self.media)
        self.assertEqual(trim_request.status, "success")
        produce_thumbnails_from_video.assert_called_once()
        produce_sprite_from_video_delay.assert_called_once_with(self.media.friendly_token)
        create_hls_delay.assert_called_once_with(self.media.friendly_token)
