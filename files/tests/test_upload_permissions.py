import os
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings

from cms.permissions import user_allowed_to_upload
from files.tests.user_utils import create_account


@override_settings(CAN_ADD_MEDIA="all")
class UploadPermissionsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request_for(self, user):
        request = self.factory.post("/api/v1/media")
        request.user = user
        return request

    def test_regular_user_cannot_upload_media(self):
        user = create_account(password="pass1234", email="regular-upload@example.com")

        self.assertFalse(user_allowed_to_upload(self._request_for(user)))

    def test_editor_cannot_upload_media(self):
        user = create_account(password="pass1234", email="editor-upload@example.com", is_editor=True)

        self.assertFalse(user_allowed_to_upload(self._request_for(user)))

    def test_manager_can_upload_media(self):
        user = create_account(password="pass1234", email="manager-upload@example.com", is_manager=True)

        self.assertTrue(user_allowed_to_upload(self._request_for(user)))

    def test_superuser_can_upload_media(self):
        user = create_account(password="pass1234", email="superuser-upload@example.com", is_superuser=True)

        self.assertTrue(user_allowed_to_upload(self._request_for(user)))

    def test_manager_cannot_upload_when_storage_limit_is_reached(self):
        user = create_account(password="pass1234", email="manager-full-storage@example.com", is_manager=True)

        with tempfile.TemporaryDirectory() as media_root:
            encoded_dir = os.path.join(media_root, "encoded")
            os.makedirs(encoded_dir)
            with open(os.path.join(encoded_dir, "full.mp4"), "wb") as handle:
                handle.write(b"xx")

            with override_settings(MEDIA_ROOT=media_root, MEDIA_STORAGE_LIMIT_GB=1 / (1024 ** 3)):
                self.assertFalse(user_allowed_to_upload(self._request_for(user)))

    def test_media_api_rejects_file_that_exceeds_remaining_storage(self):
        user = create_account(password="pass1234", email="manager-storage-post@example.com", is_manager=True)
        client = Client()
        client.force_login(user)

        upload = SimpleUploadedFile("video.mp4", b"xx", content_type="video/mp4")

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, MEDIA_STORAGE_LIMIT_GB=1 / (1024 ** 3)):
                response = client.post("/api/v1/media", {"media_file": upload, "title": "Video"})

        self.assertEqual(response.status_code, 403)
        self.assertIn("almacenamiento", response.json()["detail"])
