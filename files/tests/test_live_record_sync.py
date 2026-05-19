import os
import tempfile
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from files.methods import sync_live_record_media


class LiveRecordSyncTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.user = Mock()
        self.user.channels.order_by.return_value.first.return_value = Mock()

    def _create_file(self, folder, name, content=b"video-data"):
        path = os.path.join(folder, name)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    @override_settings(LIVE_RECORD_SYNC_MIN_AGE_SECONDS=0)
    def test_sync_live_record_media_skips_temporary_files(self):
        with tempfile.TemporaryDirectory() as media_root:
            folder = os.path.join(media_root, "live_record")
            os.makedirs(folder)
            self._create_file(folder, "live.mp4.temp")

            with override_settings(MEDIA_ROOT=media_root):
                with patch("files.methods.models.Media") as media_model:
                    result = sync_live_record_media(self.user, folder=folder)

        self.assertEqual(result["created"], [])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["reason"], "temporary")
        media_model.assert_not_called()

    @override_settings(LIVE_RECORD_SYNC_MIN_AGE_SECONDS=0)
    def test_sync_live_record_media_waits_until_file_is_stable(self):
        with tempfile.TemporaryDirectory() as media_root:
            folder = os.path.join(media_root, "live_record")
            os.makedirs(folder)
            self._create_file(folder, "live.mp4")

            with override_settings(MEDIA_ROOT=media_root):
                with patch("files.methods.get_file_type", return_value="video"):
                    with patch("files.methods._update_live_record_media"):
                        with patch("files.methods.models.Media") as media_model:
                            media_model.objects.filter.return_value.first.return_value = None
                            media_instance = Mock()
                            media_model.return_value = media_instance

                            first_result = sync_live_record_media(self.user, folder=folder)
                            second_result = sync_live_record_media(self.user, folder=folder)

        self.assertEqual(first_result["created"], [])
        self.assertEqual(first_result["skipped"][0]["reason"], "changing")
        self.assertEqual(len(second_result["created"]), 1)
        media_instance.save.assert_called_once()