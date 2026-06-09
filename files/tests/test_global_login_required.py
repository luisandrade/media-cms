from django.test import Client, TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from files.models import Media
from files.tests.user_utils import create_account


class GlobalLoginRequiredTests(TestCase):
    @override_settings(GLOBAL_LOGIN_REQUIRED=True)
    def test_index_redirects_anonymous_users_to_login(self):
        response = Client().get('/')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        self.assertIn('next=/', response['Location'])

    @override_settings(GLOBAL_LOGIN_REQUIRED=True)
    def test_members_page_redirects_anonymous_users_to_login(self):
        response = Client().get('/members')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        self.assertIn('next=/members', response['Location'])

    @override_settings(GLOBAL_LOGIN_REQUIRED=True)
    def test_media_page_redirects_anonymous_users_to_login(self):
        response = Client().get('/view?m=1pJ1e4IlQ')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        self.assertIn('next=/view%3Fm%3D1pJ1e4IlQ', response['Location'])

    @override_settings(GLOBAL_LOGIN_REQUIRED=True)
    def test_media_list_api_rejects_anonymous_users(self):
        response = Client().get('/api/v1/media')

        self.assertIn(response.status_code, (401, 403))

    @override_settings(GLOBAL_LOGIN_REQUIRED=True)
    def test_media_detail_api_rejects_anonymous_users(self):
        response = Client().get('/api/v1/media/1pJ1e4IlQ')

        self.assertIn(response.status_code, (401, 403))


@override_settings(GLOBAL_LOGIN_REQUIRED=True)
class MediaSubscriptionAccessTests(TestCase):
    fixtures = ["fixtures/categories.json", "fixtures/encoding_profiles.json"]

    def setUp(self):
        self.user = create_account(password="pass1234", email="viewer@example.com")
        self.admin = create_account(password="pass1234", email="admin@example.com")
        self.admin.is_superuser = True
        self.admin.is_staff = True
        self.admin.save(update_fields=["is_superuser", "is_staff"])
        media_file = SimpleUploadedFile(
            "restricted.gif",
            (
                b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04"
                b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
            ),
            content_type="image/gif",
        )
        self.media = Media.objects.create(
            user=self.admin,
            title="Video restringido",
            media_file=media_file,
            state="public",
        )

    def test_media_page_blocks_non_admin_without_subscription(self):
        client = Client()
        client.force_login(self.user)

        response = client.get(f"/view?m={self.media.friendly_token}")

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "No tienes una suscripcion activa", status_code=403)

    def test_media_detail_api_blocks_non_admin_without_subscription(self):
        client = Client()
        client.force_login(self.user)

        response = client.get(f"/api/v1/media/{self.media.friendly_token}")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["subscription_required"], True)

    def test_media_detail_api_allows_admin_without_subscription(self):
        client = Client()
        client.force_login(self.admin)

        response = client.get(f"/api/v1/media/{self.media.friendly_token}")

        self.assertEqual(response.status_code, 200)
