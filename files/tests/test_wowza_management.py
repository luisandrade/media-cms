import json
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from files.models import StreamChatMessage, WowzaApplication
from files.tests.user_utils import create_account
from files.wowza_views import hls_playlist_is_live
from files.wowza import (
    WowzaAPIError,
    WowzaClient,
    generate_wowza_publish_password,
    generate_wowza_token,
    validate_wowza_app_name,
    wowza_advanced_settings_payload,
    wowza_has_incoming_streams,
    wowza_live_application_payload,
    wowza_push_publish_map_entry_payload,
    wowza_stream_recorder_payload,
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
        self.assertEqual(app.storage_dir, "/mediavms/rodeovms/live_record")
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
        wowza_client.get_stream_recorder.return_value = {
            "recorderState": "Recording in Progress",
            "currentFile": "/mediavms/rodeovms/live_record/eventoz06_live_20260612T010000Z_1.mp4",
        }
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
        self.assertIn("/live/playlist.m3u8?", result["hls_url"])
        self.assertIn("wowzatokenhash=", result["hls_url"])
        self.assertEqual(result["is_live"], True)
        self.assertEqual(result["is_recording"], True)
        self.assertEqual(result["recording_state"], "Recording in Progress")
        self.assertIn("eventoz06_live_", result["recording_file"])
        wowza_client.incoming_streams.assert_called_once()
        wowza_client.get_stream_recorder.assert_called_once_with(app_name=result["name"])

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
        self.assertTrue(result["url"].endswith("/live/eventozlive"))
        self.assertEqual(result["stream"], "")
        self.assertEqual(result["is_live"], True)
        self.assertNotIn("publish_password", result)
        self.assertNotIn("publish_username", result)
        self.assertEqual(results_by_title["eventozoffline"]["is_live"], False)

    @patch("files.wowza_views.requests.get")
    @patch("files.wowza_views.WowzaClient")
    def test_wowza_live_page_shows_offline_without_hls_url(self, wowza_client_cls, requests_get):
        WowzaApplication.objects.create(
            name="eventozoffline",
            schedule_id="schedule-offline",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        response_404 = Mock()
        response_404.status_code = 404
        response_404.headers = {}
        response_404.text = ""
        requests_get.return_value = response_404
        wowza_client = Mock()
        wowza_client.incoming_streams.return_value = {"incomingStreams": []}
        wowza_client_cls.return_value = wowza_client
        self.client.force_login(self.admin)

        response = self.client.get("/live/eventozoffline")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Diagnóstico Wowza")
        self.assertContains(response, "/eventozoffline/live/playlist.m3u8")
        self.assertContains(response, "<video")
        self.assertContains(response, "Chat en vivo")
        self.assertNotContains(response, "Reproductor habilitado para prueba")

    @patch("files.wowza_views.WowzaClient")
    def test_wowza_live_page_uses_secure_token_when_enabled(self, wowza_client_cls):
        WowzaApplication.objects.create(
            name="eventozlive",
            schedule_id="schedule-live",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        wowza_client = Mock()
        wowza_client.incoming_streams.return_value = {"incomingStreams": [{"name": "live"}]}
        wowza_client_cls.return_value = wowza_client
        self.client.force_login(self.admin)

        response = self.client.get("/live/eventozlive")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://scl.edge.grupoz.cl/eventozlive/live/playlist.m3u8?")
        self.assertContains(response, "wowzatokenhash=")
        self.assertContains(response, "wowzatokenstarttime=0")
        self.assertContains(response, "wowzatokenendtime=")
        self.assertNotContains(response, "wowzatokenendtime=0&amp;")

    @override_settings(WOWZA_SECURE_TOKEN_ENABLED=False)
    @patch("files.wowza_views.WowzaClient")
    def test_wowza_live_page_can_disable_secure_token(self, wowza_client_cls):
        WowzaApplication.objects.create(
            name="eventozlive",
            schedule_id="schedule-live",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        wowza_client = Mock()
        wowza_client.incoming_streams.return_value = {"incomingStreams": [{"name": "live"}]}
        wowza_client_cls.return_value = wowza_client
        self.client.force_login(self.admin)

        response = self.client.get("/live/eventozlive")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'src="https://scl.edge.grupoz.cl/eventozlive/live/playlist.m3u8"')
        self.assertNotContains(response, "wowzatokenhash=")

    def test_wowza_live_page_requires_subscription_for_regular_user(self):
        WowzaApplication.objects.create(
            name="eventozlive",
            schedule_id="schedule-live",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        self.client.force_login(self.user)

        response = self.client.get("/live/eventozlive")

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "suscripciones", status_code=403)

    def test_wowza_live_chat_allows_authorized_user_to_post_and_list_messages(self):
        WowzaApplication.objects.create(
            name="eventozlive",
            schedule_id="schedule-live",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        self.client.force_login(self.admin)

        create_response = self.client.post(
            "/api/v1/wowza_live/eventozlive/chat",
            data=json.dumps({"message": "Hola desde el chat"}),
            content_type="application/json",
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.json()["message"], "Hola desde el chat")
        list_response = self.client.get("/api/v1/wowza_live/eventozlive/chat")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["results"][0]["message"], "Hola desde el chat")
        self.assertEqual(list_response.json()["can_write"], True)

    def test_wowza_live_chat_requires_subscription_for_regular_user(self):
        WowzaApplication.objects.create(
            name="eventozlive",
            schedule_id="schedule-live",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        self.client.force_login(self.user)

        response = self.client.get("/api/v1/wowza_live/eventozlive/chat")

        self.assertEqual(response.status_code, 403)

    @override_settings(WOWZA_LIVE_CHAT_ENABLED=False)
    @patch("files.wowza_views.WowzaClient")
    def test_wowza_live_page_can_disable_chat(self, wowza_client_cls):
        WowzaApplication.objects.create(
            name="eventozlive",
            schedule_id="schedule-live",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        wowza_client = Mock()
        wowza_client.incoming_streams.return_value = {"incomingStreams": [{"name": "live"}]}
        wowza_client_cls.return_value = wowza_client
        self.client.force_login(self.admin)

        response = self.client.get("/live/eventozlive")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Chat en vivo")

    def test_wowza_live_chat_allows_staff_to_delete_messages(self):
        app = WowzaApplication.objects.create(
            name="eventozlive",
            schedule_id="schedule-live",
            created_by=self.admin,
            storage_dir=f"/nas/{self.admin.id}",
        )
        message = StreamChatMessage.objects.create(stream=app, user=self.admin, message="Mensaje moderado")
        self.client.force_login(self.staff_admin)

        response = self.client.delete(f"/api/v1/wowza_live/eventozlive/chat/{message.id}")

        self.assertEqual(response.status_code, 204)
        message.refresh_from_db()
        self.assertEqual(message.is_deleted, True)
        self.assertEqual(message.deleted_by, self.staff_admin)

    def test_generate_wowza_token_uses_configured_hash_query_prefix(self):
        token = generate_wowza_token("eventozlive/live", "a3e69479cda106ac", token_name="wowzatoken")

        self.assertIn("wowzatokenhash=", token)
        self.assertIn("wowzatokenstarttime=0", token)
        self.assertIn("wowzatokenendtime=0", token)

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
        self.assertEqual(payload["streamConfig"]["streamType"], "live-record")
        self.assertEqual(payload["streamConfig"]["storageDir"], "/mediavms/rodeovms/live_record")
        self.assertEqual(
            payload["streamConfig"]["liveStreamPacketizer"],
            ["cupertinostreamingpacketizer", "sanjosestreamingpacketizer", "smoothstreamingpacketizer"],
        )

    @override_settings(WOWZA_RECORD_ALL_INCOMING_STREAMS_ENABLED=False)
    def test_live_application_payload_can_disable_record_all_incoming_streams(self):
        payload = wowza_live_application_payload(name="eventoz10", storage_user_id=1)

        self.assertEqual(payload["streamConfig"]["streamType"], "live")

    def test_advanced_settings_configures_encoder_auth_file_without_extra_auth_module(self):
        payload = wowza_advanced_settings_payload("schedule10")
        module_names = [module["name"] for module in payload["modules"]]
        settings_by_name = {setting["name"]: setting for setting in payload["advancedSettings"]}
        security_module = next(module for module in payload["modules"] if module["name"] == "ModuleCoreSecurity")
        security_password_file_setting = settings_by_name["securityPublishPasswordFile"]
        auth_setting = settings_by_name["rtmpEncoderAuthenticateFile"]

        self.assertNotIn("rtmpAuthenticate", module_names)
        self.assertNotIn("ModuleAutoRecord", module_names)
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
        self.assertEqual(settings_by_name["securitySecureTokenVersion"]["value"], 2)
        self.assertEqual(settings_by_name["securitySecureTokenVersion"]["type"], "Integer")
        self.assertEqual(settings_by_name["securitySecureTokenSharedSecret"]["value"], settings.WOWZA_LIVE_SECRET)
        self.assertEqual(settings_by_name["securitySecureTokenHashAlgorithm"]["value"], "SHA-256")
        self.assertEqual(settings_by_name["securitySecureTokenQueryParametersPrefix"]["value"], "wowzatoken")
        self.assertEqual(settings_by_name["streamRecorderSegmentationType"]["section"], "/Root/Application/StreamRecorder")
        self.assertEqual(settings_by_name["streamRecorderSegmentationType"]["value"], "duration")
        self.assertEqual(settings_by_name["streamRecorderSegmentationType"]["type"], "String")
        self.assertEqual(settings_by_name["streamRecorderSegmentDuration"]["section"], "/Root/Application/StreamRecorder")
        self.assertEqual(settings_by_name["streamRecorderSegmentDuration"]["value"], 900000)
        self.assertEqual(settings_by_name["streamRecorderSegmentDuration"]["type"], "Long")
        self.assertEqual(settings_by_name["streamRecorderFileFormat"]["value"], "mp4")
        self.assertEqual(settings_by_name["streamRecorderVersioningOption"]["value"], "version")
        self.assertEqual(
            settings_by_name["streamRecorderFileVersionTemplate"]["value"],
            "${SourceStreamName}_${RecordingStartTime}_${SegmentNumber}",
        )
        self.assertEqual(settings_by_name["streamRecorderStartOnKeyFrame"]["value"], True)
        self.assertEqual(settings_by_name["streamRecorderRecordData"]["value"], True)

    @override_settings(WOWZA_SECURE_TOKEN_ENABLED=False)
    def test_advanced_settings_can_disable_playback_secure_token(self):
        payload = wowza_advanced_settings_payload("schedule10")
        setting_names = {setting["name"] for setting in payload["advancedSettings"]}

        self.assertNotIn("securitySecureTokenVersion", setting_names)
        self.assertNotIn("securitySecureTokenSharedSecret", setting_names)
        self.assertNotIn("securitySecureTokenHashAlgorithm", setting_names)
        self.assertNotIn("securitySecureTokenQueryParametersPrefix", setting_names)

    @override_settings(WOWZA_RECORD_SEGMENT_BY_DURATION_ENABLED=False)
    def test_advanced_settings_can_disable_record_segmentation(self):
        payload = wowza_advanced_settings_payload("schedule10")
        setting_names = {setting["name"] for setting in payload["advancedSettings"]}

        self.assertNotIn("streamRecorderSegmentationType", setting_names)
        self.assertNotIn("streamRecorderSegmentDuration", setting_names)

    @override_settings(WOWZA_RECORD_SEGMENT_DURATION_SECONDS=60)
    def test_advanced_settings_uses_configured_record_segment_duration(self):
        payload = wowza_advanced_settings_payload("schedule10")
        settings_by_name = {setting["name"]: setting for setting in payload["advancedSettings"]}

        self.assertEqual(settings_by_name["streamRecorderSegmentDuration"]["value"], 60000)

    def test_stream_recorder_payload_segments_live_stream_by_duration(self):
        payload = wowza_stream_recorder_payload(app_name="eventoz10", recorder_name="live")

        self.assertEqual(payload["recorderName"], "live")
        self.assertEqual(payload["applicationName"], "eventoz10")
        self.assertEqual(payload["segmentationType"], "duration")
        self.assertEqual(payload["segmentDuration"], 900000)
        self.assertRegex(payload["baseFile"], r"^eventoz10_live_\d{8}T\d{6}Z_[a-f0-9]{6}$")
        self.assertEqual(payload["outputPath"], "/mediavms/rodeovms/live_record")
        self.assertEqual(payload["fileTemplate"], f"{payload['baseFile']}_${{SegmentNumber}}")
        self.assertNotEqual(payload["baseFile"], "live")
        self.assertEqual(
            payload["fileVersionDelegateName"],
            "com.wowza.wms.livestreamrecord.manager.StreamRecorderFileVersionDelegate",
        )
        self.assertEqual(payload["fileFormat"], "mp4")
        self.assertEqual(payload["option"], "Version existing file")

    def test_wowza_client_creates_segmented_stream_recorder_for_live_application(self):
        client = WowzaClient(base_url="http://wowza.example", username="u", password="p")
        client.request = Mock(return_value={"success": True})
        client.update_advanced_settings = Mock(return_value={"success": True})
        client.create_stream_recorder = Mock(return_value={"success": True})
        client.create_push_publish_map_entry = Mock(return_value={"success": True})
        client.create_publisher = Mock(return_value={"success": True})

        result = client.create_live_application(
            name="eventoz10",
            storage_user_id=1,
            schedule_id="schedule10",
            publish_username="eventoz10",
            publish_password="secret",
        )

        self.assertEqual(result["stream_recorder"], {"success": True})
        client.create_stream_recorder.assert_called_once_with(app_name="eventoz10")

    @override_settings(WOWZA_RECORD_SEGMENT_BY_DURATION_ENABLED=False)
    def test_wowza_client_can_skip_segmented_stream_recorder(self):
        client = WowzaClient(base_url="http://wowza.example", username="u", password="p")
        client.request = Mock(return_value={"success": True})
        client.update_advanced_settings = Mock(return_value={"success": True})
        client.create_stream_recorder = Mock(return_value={"success": True})
        client.create_push_publish_map_entry = Mock(return_value={"success": True})
        client.create_publisher = Mock(return_value={"success": True})

        result = client.create_live_application(
            name="eventoz10",
            storage_user_id=1,
            schedule_id="schedule10",
            publish_username="eventoz10",
            publish_password="secret",
        )

        self.assertIsNone(result["stream_recorder"])
        client.create_stream_recorder.assert_not_called()

    @patch("files.wowza_views.WowzaClient")
    def test_start_recording_endpoint_starts_segmented_stream_recorder(self, wowza_client_cls):
        app = WowzaApplication.objects.create(
            name="eventozrecord",
            schedule_id="schedule-record",
            created_by=self.admin,
            storage_dir="/mediavms/rodeovms/live_record",
        )
        wowza_client = Mock()
        wowza_client.start_stream_recording.return_value = {"success": True, "recorderName": "live"}
        wowza_client_cls.return_value = wowza_client
        self.client.force_login(self.admin)

        response = self.client.post(f"/api/v1/manage_wowza/applications/{app.id}/recording")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["success"], True)
        self.assertEqual(response.json()["is_recording"], True)
        self.assertEqual(response.json()["data"], {"success": True, "recorderName": "live"})
        wowza_client.start_stream_recording.assert_called_once_with(app_name="eventozrecord")

    @patch("files.wowza_views.WowzaClient")
    def test_stop_recording_endpoint_stops_segmented_stream_recorder(self, wowza_client_cls):
        app = WowzaApplication.objects.create(
            name="eventozrecord",
            schedule_id="schedule-record",
            created_by=self.admin,
            storage_dir="/mediavms/rodeovms/live_record",
        )
        wowza_client = Mock()
        wowza_client.stop_stream_recording.return_value = {"success": True}
        wowza_client_cls.return_value = wowza_client
        self.client.force_login(self.admin)

        response = self.client.delete(f"/api/v1/manage_wowza/applications/{app.id}/recording")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["success"], True)
        self.assertEqual(response.json()["is_recording"], False)
        wowza_client.stop_stream_recording.assert_called_once_with(app_name="eventozrecord")

    def test_start_recording_endpoint_rejects_non_admin(self):
        app = WowzaApplication.objects.create(
            name="eventozrecord",
            schedule_id="schedule-record",
            created_by=self.admin,
            storage_dir="/mediavms/rodeovms/live_record",
        )
        self.client.force_login(self.user)

        response = self.client.post(f"/api/v1/manage_wowza/applications/{app.id}/recording")

        self.assertEqual(response.status_code, 403)

    @override_settings(
        WOWZA_PUSH_PUBLISH_ENTRY_NAME="live",
        WOWZA_PUSH_PUBLISH_PROFILE="rtmp",
        WOWZA_PUSH_PUBLISH_APPLICATION="miradio2restream",
        WOWZA_PUSH_PUBLISH_DESTINATION_NAME="wowzastreamingengine",
        WOWZA_PUSH_PUBLISH_HOST="scl.edge.grupoz.cl",
        WOWZA_PUSH_PUBLISH_STREAM_NAME="live",
    )
    def test_push_publish_map_entry_payload_uses_current_app_name(self):
        payload = wowza_push_publish_map_entry_payload(app_name="eventoz10")

        self.assertEqual(
            payload,
            {
                "entryName": "live",
                "profile": "rtmp",
                "application": "eventoz10",
                "destinationName": "wowzastreamingengine",
                "host": "scl.edge.grupoz.cl",
                "streamName": "live",
            },
        )

    @override_settings(WOWZA_PUSH_PUBLISH_APPLICATION="miradio2restream")
    def test_push_publish_map_entry_payload_keeps_legacy_default_without_app_name(self):
        payload = wowza_push_publish_map_entry_payload()

        self.assertEqual(payload["application"], "miradio2restream")

    def test_generate_publish_password_uses_10_characters_by_default(self):
        password = generate_wowza_publish_password()

        self.assertEqual(len(password), 10)

    def test_wowza_has_incoming_streams_detects_live_payload(self):
        self.assertEqual(wowza_has_incoming_streams({"incomingStreams": [{"name": "live"}]}), True)
        self.assertEqual(wowza_has_incoming_streams({"incomingStream": {"name": "live", "isConnected": True}}), True)
        self.assertEqual(wowza_has_incoming_streams({"server": {"stream": {"name": "live"}}}), True)
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
                {"stream_recorder": True},
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
        self.assertEqual(response["stream_recorder"], {"stream_recorder": True})
        self.assertEqual(response["push_publish_map_entry"], {"push_publish_map_entry": True})
        self.assertEqual(request.call_count, 6)
        self.assertEqual(request.call_args_list[1][0][0], "PUT")
        self.assertEqual(request.call_args_list[1][0][1], "applications/eventoz11")
        self.assertEqual(request.call_args_list[1][0][2]["securityConfig"]["publishRequirePassword"], True)
        self.assertEqual(request.call_args_list[3][0][0], "POST")
        self.assertEqual(request.call_args_list[3][0][1], "applications/eventoz11/instances/_definst_/streamrecorders/live")
        self.assertEqual(request.call_args_list[3][0][2]["segmentationType"], "duration")
        self.assertEqual(request.call_args_list[4][0][0], "POST")
        self.assertEqual(request.call_args_list[4][0][1], "applications/eventoz11/pushpublish/mapentries")
        self.assertEqual(request.call_args_list[4][0][2]["application"], "eventoz11")

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
