import json
from unittest.mock import Mock, patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from files.models import WowzaApplication
from files.tests.user_utils import create_account
from files.wowza_views import hls_playlist_is_live
from files.wowza import (
    WowzaAPIError,
    WowzaClient,
    generate_wowza_publish_password,
    validate_wowza_app_name,
    wowza_advanced_settings_payload,
    wowza_has_incoming_streams,
    wowza_live_application_payload,
    wowza_push_publish_map_entry_payload,
)


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

    @patch("files.wowza_views.WowzaClient")
    def test_list_applications_returns_only_saved_platform_apps(self, wowza_client_cls):
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
        wowza_client = Mock()
        wowza_client.incoming_streams.return_value = {"incomingStreams": [{"name": "live"}]}
        wowza_client_cls.return_value = wowza_client
        self.client.force_login(self.admin)

        response = self.client.get("/api/v1/manage_wowza/applications?page=1&page_size=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["success"], True)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(response.json()["max_applications"], 10)
        self.assertEqual(response.json()["available_applications"], 8)
        self.assertEqual(response.json()["page"], 1)
        self.assertEqual(response.json()["page_size"], 1)
        self.assertEqual(len(response.json()["results"]), 1)
        result = response.json()["results"][0]
        self.assertIn("publish_password", result)
        self.assertIn("rtmp_url", result)
        self.assertIn("stream_name", result)
        self.assertTrue(result["hls_url"].startswith("https://"))
        self.assertNotIn(":1935", result["hls_url"])
        self.assertTrue(result["hls_url"].endswith("/live/playlist.m3u8"))
        self.assertEqual(result["is_live"], True)
        wowza_client.incoming_streams.assert_called_once()

    @patch("files.wowza_views.requests.get")
    @patch("files.wowza_views.WowzaClient")
    def test_public_live_applications_list_returns_safe_media_items(self, wowza_client_cls, requests_get):
        app = WowzaApplication.objects.create(
            name="eventozlive",
            schedule_id="schedule-live",
            publish_username="eventozlive",
            publish_password="Secret123",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        WowzaApplication.objects.create(
            name="eventozoffline",
            schedule_id="schedule-offline",
            publish_username="eventozoffline",
            publish_password="Secret456",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        response_404 = Mock()
        response_404.status_code = 404
        response_404.headers = {}
        response_404.text = ""
        requests_get.return_value = response_404
        wowza_client = Mock()
        wowza_client.incoming_streams.side_effect = [
            {"incomingStreams": []},
            {"incomingStreams": [{"name": "live"}]},
        ]
        wowza_client_cls.return_value = wowza_client
        self.client.force_login(self.user)

        response = self.client.get("/api/v1/wowza_live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        results_by_title = {result["title"]: result for result in response.json()["results"]}
        result = results_by_title["eventozlive"]
        self.assertEqual(result["id"], f"wowza-{app.id}")
        self.assertEqual(result["title"], "eventozlive")
        self.assertEqual(result["media_type"], "video")
        self.assertEqual(result["stream"], "https://scl.edge.grupoz.cl/eventozlive/live/playlist.m3u8")
        self.assertEqual(result["is_live"], True)
        self.assertNotIn("publish_password", result)
        self.assertNotIn("publish_username", result)
        self.assertEqual(results_by_title["eventozoffline"]["is_live"], False)

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

    @override_settings(WOWZA_MAX_APPLICATIONS=1)
    @patch("files.wowza_views.WowzaClient")
    def test_create_application_rejects_when_max_applications_is_reached(self, wowza_client_cls):
        WowzaApplication.objects.create(
            name="eventoz10",
            schedule_id="schedule10",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            "/api/v1/manage_wowza/applications",
            data=json.dumps({"name": "eventoz11"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["success"], False)
        self.assertIn("1 aplicaciones", response.json()["message"])
        wowza_client_cls.assert_not_called()

    def test_wowza_app_name_validator_rejects_forbidden_wowza_characters(self):
        invalid_names = [
            "bad<name",
            "bad>name",
            "bad:name",
            "bad'name",
            'bad"name',
            "bad/name",
            "bad\\name",
            "bad|name",
            "bad?name",
            "bad*name",
            "bad..name",
            "bad~name",
        ]

        for name in invalid_names:
            with self.subTest(name=name):
                with self.assertRaisesMessage(ValueError, "no puede contener"):
                    validate_wowza_app_name(name)

    def test_wowza_app_name_validator_allows_names_without_forbidden_characters(self):
        self.assertEqual(validate_wowza_app_name("evento.live 01"), "evento.live 01")

    def test_live_application_payload_requires_publish_password(self):
        payload = wowza_live_application_payload(name="eventoz10", storage_user_id=1)

        self.assertEqual(payload["securityConfig"]["publishRequirePassword"], True)
        self.assertEqual(payload["securityConfig"]["publishAuthenticationMethod"], "digest")
        self.assertEqual(
            payload["securityConfig"]["publishPasswordFile"],
            "${com.wowza.wms.context.VHostConfigHome}/conf/${com.wowza.wms.context.Application}/publish.password",
        )
        self.assertEqual(
            payload["streamConfig"]["liveStreamPacketizer"],
            ["cupertinostreamingpacketizer", "sanjosestreamingpacketizer", "smoothstreamingpacketizer"],
        )

    def test_advanced_settings_configures_encoder_auth_file_without_extra_auth_module(self):
        payload = wowza_advanced_settings_payload("schedule10")
        module_names = [module["name"] for module in payload["modules"]]
        security_module = next(module for module in payload["modules"] if module["name"] == "ModuleCoreSecurity")
        security_password_file_setting = next(
            setting for setting in payload["advancedSettings"] if setting["name"] == "securityPublishPasswordFile"
        )
        auth_setting = next(
            setting for setting in payload["advancedSettings"] if setting["name"] == "rtmpEncoderAuthenticateFile"
        )

        self.assertNotIn("rtmpAuthenticate", module_names)
        self.assertEqual(security_module["class"], "com.wowza.wms.security.ModuleCoreSecurity")
        self.assertEqual(security_password_file_setting["section"], "/Root/Application")
        self.assertEqual(security_password_file_setting["type"], "String")
        self.assertEqual(
            security_password_file_setting["value"],
            "${com.wowza.wms.context.VHostConfigHome}/conf/${com.wowza.wms.context.Application}/publish.password",
        )
        self.assertEqual(auth_setting["section"], "/Root/Application")
        self.assertEqual(auth_setting["type"], "String")
        self.assertEqual(
            auth_setting["value"],
            "${com.wowza.wms.context.VHostConfigHome}/conf/${com.wowza.wms.context.Application}/publish.password",
        )

    @override_settings(
        WOWZA_PUSH_PUBLISH_ENTRY_NAME="live",
        WOWZA_PUSH_PUBLISH_PROFILE="rtmp",
        WOWZA_PUSH_PUBLISH_APPLICATION="miradio2restream",
        WOWZA_PUSH_PUBLISH_DESTINATION_NAME="wowzastreamingengine",
        WOWZA_PUSH_PUBLISH_HOST="scl.edge.grupoz.cl",
        WOWZA_PUSH_PUBLISH_STREAM_NAME="live",
    )
    def test_push_publish_map_entry_payload_uses_configured_destination(self):
        payload = wowza_push_publish_map_entry_payload()

        self.assertEqual(
            payload,
            {
                "entryName": "live",
                "profile": "rtmp",
                "application": "miradio2restream",
                "destinationName": "wowzastreamingengine",
                "host": "scl.edge.grupoz.cl",
                "streamName": "live",
            },
        )

    def test_generate_publish_password_uses_10_characters_by_default(self):
        password = generate_wowza_publish_password()

        self.assertEqual(len(password), 10)

    def test_wowza_has_incoming_streams_detects_live_payload(self):
        self.assertEqual(wowza_has_incoming_streams({"incomingStreams": [{"name": "live"}]}), True)
        self.assertEqual(wowza_has_incoming_streams({"incomingStreams": []}), False)

    @patch("files.wowza_views.requests.get")
    def test_hls_playlist_is_live_detects_valid_playlist(self, requests_get):
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/vnd.apple.mpegurl"}
        response.text = "#EXTM3U\n#EXT-X-VERSION:3\n"
        requests_get.return_value = response

        self.assertEqual(hls_playlist_is_live("https://scl.edge.grupoz.cl/app/live/playlist.m3u8"), True)

    @patch("files.wowza_views.requests.get")
    def test_hls_playlist_is_live_rejects_missing_playlist(self, requests_get):
        response = Mock()
        response.status_code = 404
        response.headers = {}
        response.text = ""
        requests_get.return_value = response

        self.assertEqual(hls_playlist_is_live("https://scl.edge.grupoz.cl/app/live/playlist.m3u8"), False)

    def test_wowza_client_continues_when_application_already_exists(self):
        client = WowzaClient(base_url="http://wowza.test", username="u", password="p")
        with patch.object(client, "request") as request:
            request.side_effect = [
                WowzaAPIError("conflict", status_code=409, data={"code": "409"}),
                {"updated": True},
                {"advanced": True},
                {"push_publish_map_entry": True},
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
        self.assertEqual(response["application"]["message"], "La aplicación ya existía en Wowza y fue actualizada.")
        self.assertEqual(response["application"]["updated"], {"updated": True})
        self.assertEqual(response["push_publish_map_entry"], {"push_publish_map_entry": True})
        self.assertEqual(request.call_count, 5)
        self.assertEqual(request.call_args_list[1][0][0], "PUT")
        self.assertEqual(request.call_args_list[1][0][1], "applications/eventoz11")
        self.assertEqual(request.call_args_list[1][0][2]["securityConfig"]["publishRequirePassword"], True)
        self.assertEqual(request.call_args_list[3][0][0], "POST")
        self.assertEqual(request.call_args_list[3][0][1], "applications/eventoz11/pushpublish/mapentries")

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
