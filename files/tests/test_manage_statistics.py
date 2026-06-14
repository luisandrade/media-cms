import os
import tempfile

from django.test import TestCase, override_settings

from files.models import Comment, Media, WowzaApplication
from files.tests.user_utils import create_account
from payments.models import FlowCustomer, SubscriptionPlan, UserSubscription


class ManageStatisticsTests(TestCase):
    def _write_file(self, folder, filename, size):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, filename)

        with open(path, "wb") as handle:
            handle.write(b"x" * size)

        return path

    def test_statistics_reports_encoded_and_live_record_storage_usage(self):
        with tempfile.TemporaryDirectory() as media_root:
            encoded_dir = os.path.join(media_root, "encoded")
            live_record_dir = os.path.join(media_root, "live_record")
            self._write_file(encoded_dir, "encoded.mp4", 1024)
            self._write_file(live_record_dir, "recorded.mp4", 2048)
            self._write_file(os.path.join(media_root, "original"), "original.mp4", 4096)

            with override_settings(MEDIA_ROOT=media_root, MEDIA_STORAGE_LIMIT_GB=1):
                user = create_account(
                    email="stats-admin@example.com",
                    password="pass1234",
                    is_superuser=True,
                )
                subscriber = create_account(email="subscriber@example.com", password="pass1234")
                plan = SubscriptionPlan.objects.create(
                    flow_plan_id="plan-stats",
                    name="Plan Stats",
                    amount=1000,
                )
                customer = FlowCustomer.objects.create(
                    user=subscriber,
                    flow_customer_id="cus_stats",
                    external_id=str(subscriber.id),
                    email=subscriber.email,
                    name=subscriber.name,
                )
                UserSubscription.objects.create(
                    user=subscriber,
                    plan=plan,
                    customer=customer,
                    flow_subscription_id="sub_stats",
                    status=UserSubscription.STATUS_ACTIVE,
                    flow_status=UserSubscription.FLOW_STATUS_ACTIVE,
                    morose=0,
                )
                media = Media.objects.create(user=user, title="Video stats", media_file="original/video.mp4")
                Comment.objects.create(user=user, media=media, text="Primer comentario")
                Comment.objects.create(user=subscriber, media=media, text="Segundo comentario")
                WowzaApplication.objects.create(name="live-stats-1", schedule_id="schedule-1", is_active=True)
                WowzaApplication.objects.create(name="live-stats-2", schedule_id="schedule-2", is_active=True)
                WowzaApplication.objects.create(name="live-stats-disabled", schedule_id="schedule-3", is_active=False)
                self.client.force_login(user)

                response = self.client.get("/api/v1/manage_statistics")

        self.assertEqual(response.status_code, 200)
        storage_usage = response.json()["storage_usage"]
        self.assertEqual(storage_usage["used_bytes"], 3072)
        self.assertEqual(storage_usage["limit_bytes"], 1024 ** 3)
        self.assertEqual(storage_usage["remaining_bytes"], 1024 ** 3 - 3072)
        self.assertEqual(storage_usage["folders"], ["encoded", "live_record"])
        self.assertEqual(response.json()["total_subscribers"], 1)
        self.assertEqual(response.json()["total_comments"], 2)
        self.assertEqual(response.json()["total_live_signals"], 2)
