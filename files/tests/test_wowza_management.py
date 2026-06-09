import json
from unittest.mock import Mock, patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from files.models import WowzaApplication
from files.tests.user_utils import create_account
from files.wowza import WowzaAPIError, WowzaClient, generate_wowza_publish_password, wowza_live_application_payload


class WowzaManagementTests(TestCase):
    fixtures = ["fixtures/categories.json", "fixtures/encoding_profiles.json"]

    def setUp(self):
        self.client = Client()
        self.user = create_account(username="viewerwowza", password="pass1234", email="viewer-wowza@example.com")
        self.admin = create_account(
            username="adminwowza",
            password="pass1234",
            email="admin-wowza@example.com",
            is_superuser=True,
        )
        self.staff_admin = create_account(
            username="staffwowza",
            password="pass1234",
            email="staff-wowza@example.com",
        )
        self.staff_admin.is_staff = True
        self.staff_admin.save(update_fields=["is_staff"])

    def test_manage_wowza_page_requires_admin(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("manage_wowza"))

        self.assertEqual(response.status_code, 403)

    def test_manage_wowza_page_allows_admin(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("manage_wowza"))

        self.assertEqual(response.status_code, 200)

    def test_manage_wowza_page_allows_staff_admin(self):
        self.client.force_login(self.staff_admin)

        response = self.client.get(reverse("manage_wowza"))

        self.assertEqual(response.status_code, 200)

    def test_create_application_rejects_non_admin(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/api/v1/manage_wowza/applications",
            data=json.dumps({"name": "eventoz06"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    @patch("files.wowza_views.generate_wowza_publish_password")
    @patch("files.wowza_views.WowzaClient")
    def test_create_application_uses_wowza_client_for_admin(self, wowza_client_cls, generate_password):
        generate_password.return_value = "SecurePass1234567890"
        wowza_client = Mock()
        wowza_client.create_live_application.return_value = {"success": True, "application": {"name": "eventoz06"}}
        wowza_client_cls.return_value = wowza_client
        self.client.force_login(self.admin)

        response = self.client.post(
            "/api/v1/manage_wowza/applications",
            data=json.dumps({"name": "eventoz06", "schedule_id": "schedule06", "storage_user_id": "999"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["success"], True)
        app = WowzaApplication.objects.get(name="eventoz06")
        self.assertEqual(app.schedule_id, "schedule06")
        self.assertEqual(app.created_by, self.admin)
        self.assertEqual(app.storage_dir, f"/nas/{self.admin.id}")
        self.assertEqual(app.publish_username, "eventoz06")
        self.assertEqual(app.publish_password, "SecurePass1234567890")
        wowza_client.create_live_application.assert_called_once_with(
            name="eventoz06",
            storage_user_id=self.admin.id,
            schedule_id="schedule06",
            publish_username="eventoz06",
            publish_password="SecurePass1234567890",
        )

    def test_list_applications_returns_only_saved_platform_apps(self):
        WowzaApplication.objects.create(
            name="eventoz06",
            schedule_id="schedule06",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        WowzaApplication.objects.create(
            name="eventoz07",
            schedule_id="schedule07",
            created_by=self.staff_admin,
            storage_dir=f"/nas/{self.staff_admin.id}",
        )
        self.client.force_login(self.admin)

        response = self.client.get("/api/v1/manage_wowza/applications?page=1&page_size=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["success"], True)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(response.json()["page"], 1)
        self.assertEqual(response.json()["page_size"], 1)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertIn("publish_password", response.json()["results"][0])

    @patch("files.wowza_views.WowzaClient")
    def test_delete_application_calls_wowza_and_removes_saved_app(self, wowza_client_cls):
        app = WowzaApplication.objects.create(
            name="eventoz08",
            schedule_id="schedule08",
            publish_username="eventoz08",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        wowza_client = Mock()
        wowza_client.delete_live_application.return_value = {"success": True}
        wowza_client_cls.return_value = wowza_client
        self.client.force_login(self.admin)

        response = self.client.delete(f"/api/v1/manage_wowza/applications/{app.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["success"], True)
        self.assertFalse(WowzaApplication.objects.filter(id=app.id).exists())
        wowza_client.delete_publisher.assert_called_once_with(app_name="eventoz08", publisher_name="eventoz08")
        wowza_client.delete_live_application.assert_called_once_with(name="eventoz08")

    def test_delete_application_rejects_non_admin(self):
        app = WowzaApplication.objects.create(
            name="eventoz09",
            schedule_id="schedule09",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        self.client.force_login(self.user)

        response = self.client.delete(f"/api/v1/manage_wowza/applications/{app.id}")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(WowzaApplication.objects.filter(id=app.id).exists())

    def test_create_application_validates_app_name(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            "/api/v1/manage_wowza/applications",
            data=json.dumps({"name": "../bad"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["success"], False)

    @override_settings(WOWZA_PUBLISH_AUTH_METHOD="digest", WOWZA_PUBLISH_PASSWORD_FILE="")
    def test_live_application_payload_requires_publish_password(self):
        payload = wowza_live_application_payload(name="eventoz10", storage_user_id=1)

        self.assertEqual(payload["securityConfig"]["publishRequirePassword"], True)
        self.assertEqual(payload["securityConfig"]["publishAuthenticationMethod"], "digest")

    def test_generate_publish_password_uses_10_characters_by_default(self):
        password = generate_wowza_publish_password()

        self.assertEqual(len(password), 10)

    def test_wowza_client_continues_when_application_already_exists(self):
        client = WowzaClient(base_url="http://wowza.test", username="u", password="p")
        with patch.object(client, "request") as request:
            request.side_effect = [
                WowzaAPIError("conflict", status_code=409, data={"code": "409"}),
                {"advanced": True},
                {"publisher": True},
            ]

            response = client.create_live_application(
                name="eventoz11",
                storage_user_id=1,
                schedule_id="schedule11",
                publish_username="eventoz11",
                publish_password="SecurePass1234567890",
            )

        self.assertEqual(response["success"], True)
        self.assertEqual(response["application"]["message"], "La aplicación ya existía en Wowza.")
        self.assertEqual(request.call_count, 3)

    def test_wowza_client_updates_publisher_when_it_already_exists(self):
        client = WowzaClient(base_url="http://wowza.test", username="u", password="p")
        with patch.object(client, "request") as request:
            request.side_effect = [
                WowzaAPIError("conflict", status_code=409, data={"code": "409"}),
                {"updated": True},
            ]

            response = client.create_publisher(
                app_name="eventoz12",
                publisher_name="eventoz12",
                password="SecurePass1234567890",
            )

        self.assertEqual(response["success"], True)
        self.assertEqual(response["message"], "El publisher ya existía en Wowza y fue actualizado.")
        self.assertEqual(request.call_args_list[1][0][0], "PUT")
