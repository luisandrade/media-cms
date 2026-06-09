from django.test import RequestFactory, TestCase, override_settings

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