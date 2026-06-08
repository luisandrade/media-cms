from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, override_settings

from files.serializers import SingleMediaSerializer
from payments.views import video_download_is_enabled, video_download_requires_payment


class VideoDownloadSettingsTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _build_serializer(self):
        request = self.factory.get("/api/v1/media/test-token")
        request.user = AnonymousUser()
        return SingleMediaSerializer(context={"request": request})

    def test_serializer_hides_video_download_when_globally_disabled(self):
        serializer = self._build_serializer()
        media = SimpleNamespace(
            media_type="video",
            allow_download=True,
            original_media_url="/media/original.mp4",
        )

        with override_settings(VIDEO_DOWNLOAD_ENABLED=False, VIDEO_DOWNLOAD_REQUIRES_PAYMENT=True):
            self.assertFalse(serializer.get_allow_download(media))
            self.assertEqual(serializer.get_download_options(media), [])
            self.assertIsNone(serializer.get_original_media_url(media))
            self.assertFalse(serializer.get_download_requires_payment(media))

    def test_payment_helpers_respect_global_video_download_flag(self):
        media = SimpleNamespace(media_type="video", allow_download=True)

        with override_settings(VIDEO_DOWNLOAD_ENABLED=False, VIDEO_DOWNLOAD_REQUIRES_PAYMENT=True):
            self.assertFalse(video_download_is_enabled(media))
            self.assertFalse(video_download_requires_payment(media))

        with override_settings(VIDEO_DOWNLOAD_ENABLED=True, VIDEO_DOWNLOAD_REQUIRES_PAYMENT=True):
            self.assertTrue(video_download_is_enabled(media))
            self.assertTrue(video_download_requires_payment(media))
