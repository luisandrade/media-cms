from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from files.tests.user_utils import create_account
from payments.flow import FlowRedirectResult
from payments.models import FlowCustomer, SubscriptionPlan, UserSubscription, user_has_active_subscription


@override_settings(
    FLOW_SUBSCRIPTION_ENABLED=True,
    FLOW_SUBSCRIPTION_PLAN_ID="media-cms-monthly",
    FLOW_SUBSCRIPTION_PLAN_NAME="Suscripción mensual",
    FLOW_SUBSCRIPTION_PRICE_CLP=1200,
    FLOW_SUBSCRIPTION_CURRENCY="CLP",
    FLOW_SUBSCRIPTION_INTERVAL=3,
    FLOW_SUBSCRIPTION_INTERVAL_COUNT=1,
    FLOW_SUBSCRIPTION_TRIAL_DAYS=0,
)
class SubscriptionViewsTests(TestCase):
    fixtures = ["fixtures/categories.json", "fixtures/encoding_profiles.json"]

    def setUp(self):
        self.password = "pass1234"
        self.user = create_account(password=self.password, email="subscription@example.com")
        self.client.force_login(self.user)

    def test_active_subscription_requires_flow_subscription_id_and_active_flow_status(self):
        plan = SubscriptionPlan.objects.create(
            flow_plan_id="media-cms-monthly",
            name="Suscripción mensual",
            amount=1200,
            currency="CLP",
            interval=3,
        )
        customer = FlowCustomer.objects.create(
            user=self.user,
            flow_customer_id="cus_123",
            external_id=f"user-{self.user.pk}",
            email=self.user.email,
            name=self.user.name,
        )
        subscription = UserSubscription.objects.create(
            user=self.user,
            customer=customer,
            plan=plan,
            status=UserSubscription.STATUS_ACTIVE,
        )

        self.assertFalse(subscription.is_active)
        self.assertFalse(user_has_active_subscription(self.user))

        subscription.flow_subscription_id = "sus_123"
        subscription.flow_status = UserSubscription.FLOW_STATUS_INACTIVE
        subscription.last_synced_at = timezone.now()
        subscription.save(update_fields=["flow_subscription_id", "flow_status", "last_synced_at", "updated_at"])
        self.user.refresh_from_db()
        self.assertFalse(subscription.is_active)
        self.assertFalse(user_has_active_subscription(self.user))

        subscription.flow_status = UserSubscription.FLOW_STATUS_ACTIVE
        subscription.save(update_fields=["flow_status", "updated_at"])
        self.user.refresh_from_db()
        self.assertTrue(subscription.is_active)
        self.assertTrue(user_has_active_subscription(self.user))

        subscription.morose = 1
        subscription.save(update_fields=["morose", "updated_at"])
        self.user.refresh_from_db()
        self.assertFalse(subscription.is_active)
        self.assertFalse(user_has_active_subscription(self.user))

    @patch("payments.flow.FlowClient")
    def test_user_has_active_subscription_syncs_morose_status_from_flow(self, flow_client_cls):
        plan = SubscriptionPlan.objects.create(
            flow_plan_id="media-cms-monthly",
            name="Suscripción mensual",
            amount=1200,
            currency="CLP",
            interval=3,
        )
        customer = FlowCustomer.objects.create(
            user=self.user,
            flow_customer_id="cus_123",
            external_id=f"user-{self.user.pk}",
            email=self.user.email,
            name=self.user.name,
        )
        UserSubscription.objects.create(
            user=self.user,
            customer=customer,
            plan=plan,
            status=UserSubscription.STATUS_ACTIVE,
            flow_status=UserSubscription.FLOW_STATUS_ACTIVE,
            flow_subscription_id="sus_123",
            morose=0,
        )
        flow_client = Mock()
        flow_client.get_subscription.return_value = {
            "subscriptionId": "sus_123",
            "planId": "media-cms-monthly",
            "customerId": "cus_123",
            "status": 1,
            "morose": 1,
            "cancel_at_period_end": 0,
        }
        flow_client_cls.return_value = flow_client

        self.assertFalse(user_has_active_subscription(self.user))

        subscription = UserSubscription.objects.get(user=self.user)
        self.assertEqual(subscription.morose, 1)
        self.assertFalse(subscription.is_active)

    @patch("payments.views.FlowClient")
    def test_activate_subscription_redirects_to_flow_register(self, flow_client_cls):
        flow_client = Mock()
        flow_client.is_configured.return_value = True
        flow_client.get_plan.return_value = {"planId": "media-cms-monthly"}
        flow_client.create_customer.return_value = {
            "customerId": "cus_123",
            "externalId": f"user-{self.user.pk}",
            "email": self.user.email,
            "name": self.user.name,
            "status": "0",
        }
        flow_client.register_customer.return_value = FlowRedirectResult(
            redirect_url="https://flow.test/register?token=tok_123",
            token="tok_123",
            raw={"url": "https://flow.test/register", "token": "tok_123"},
        )
        flow_client_cls.return_value = flow_client

        response = self.client.post(reverse("subscription_activate"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://flow.test/register?token=tok_123")

        customer = FlowCustomer.objects.get(user=self.user)
        subscription = UserSubscription.objects.get(user=self.user)
        self.assertEqual(customer.flow_customer_id, "cus_123")
        self.assertEqual(subscription.status, UserSubscription.STATUS_PENDING_CARD)
        self.assertEqual(subscription.register_token, "tok_123")
        self.assertEqual(subscription.plan.flow_plan_id, "media-cms-monthly")

    @patch("payments.views.FlowClient")
    def test_activate_subscription_handles_nullable_flow_customer_fields(self, flow_client_cls):
        flow_client = Mock()
        flow_client.is_configured.return_value = True
        flow_client.get_plan.return_value = {"planId": "media-cms-monthly"}
        flow_client.create_customer.return_value = {
            "customerId": "cus_456",
            "externalId": f"user-{self.user.pk}",
            "email": self.user.email,
            "name": self.user.name,
            "pay_mode": "manual",
            "status": 1,
            "creditCardType": None,
            "last4CardDigits": None,
            "cardNumber": None,
            "issuerBank": None,
        }
        flow_client.register_customer.return_value = FlowRedirectResult(
            redirect_url="https://flow.test/register?token=tok_456",
            token="tok_456",
            raw={"url": "https://flow.test/register", "token": "tok_456"},
        )
        flow_client_cls.return_value = flow_client

        response = self.client.post(reverse("subscription_activate"))

        self.assertEqual(response.status_code, 302)
        customer = FlowCustomer.objects.get(user=self.user)
        self.assertEqual(customer.flow_customer_id, "cus_456")
        self.assertEqual(customer.credit_card_type, "")
        self.assertEqual(customer.last4_card_digits, "")
        self.assertEqual(customer.card_number, "")
        self.assertEqual(customer.issuer_bank, "")

    @patch("payments.views.FlowClient")
    def test_activate_subscription_restores_duplicate_flow_customer_and_registers_card(self, flow_client_cls):
        flow_client = Mock()
        flow_client.is_configured.return_value = True
        flow_client.get_plan.return_value = {"planId": "media-cms-monthly"}
        flow_client.create_customer.return_value = {
            "error": f"There is a customer with this externalId: user-{self.user.pk}",
        }
        flow_client.get_customer_subscriptions.return_value = {"total": 0, "hasMore": 0, "data": []}
        flow_client.list_customers.return_value = {
            "total": 1,
            "hasMore": 0,
            "data": [
                {
                    "customerId": "cus_existing_in_flow",
                    "externalId": f"user-{self.user.pk}",
                    "email": self.user.email,
                    "name": self.user.name,
                    "status": "1",
                }
            ],
        }
        flow_client.register_customer.return_value = FlowRedirectResult(
            redirect_url="https://flow.test/register?token=tok_existing",
            token="tok_existing",
            raw={"url": "https://flow.test/register", "token": "tok_existing"},
        )
        flow_client_cls.return_value = flow_client

        response = self.client.post(reverse("subscription_activate"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://flow.test/register?token=tok_existing")
        customer = FlowCustomer.objects.get(user=self.user)
        subscription = UserSubscription.objects.get(user=self.user)
        self.assertEqual(customer.flow_customer_id, "cus_existing_in_flow")
        self.assertEqual(customer.external_id, f"user-{self.user.pk}")
        self.assertEqual(subscription.customer, customer)
        self.assertEqual(subscription.status, UserSubscription.STATUS_PENDING_CARD)
        self.assertEqual(subscription.register_token, "tok_existing")

    @patch("payments.views.FlowClient")
    def test_activate_subscription_with_existing_pending_flow_customer_retries_card_registration(self, flow_client_cls):
        customer = FlowCustomer.objects.create(
            user=self.user,
            flow_customer_id="cus_existing",
            external_id=f"user-{self.user.pk}",
            email=self.user.email,
            name=self.user.name,
        )

        flow_client = Mock()
        flow_client.is_configured.return_value = True
        flow_client.get_plan.return_value = {"planId": "media-cms-monthly"}
        flow_client.get_customer_subscriptions.return_value = {"total": 0, "hasMore": 0, "data": []}
        flow_client.register_customer.return_value = FlowRedirectResult(
            redirect_url="https://flow.test/register?token=tok_retry",
            token="tok_retry",
            raw={"url": "https://flow.test/register", "token": "tok_retry"},
        )
        flow_client_cls.return_value = flow_client

        response = self.client.post(reverse("subscription_activate"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://flow.test/register?token=tok_retry")
        flow_client.create_customer.assert_not_called()
        flow_client.register_customer.assert_called_once_with(
            customer_id="cus_existing",
            url_return="http://testserver" + reverse("subscription_register_return"),
        )
        subscription = UserSubscription.objects.get(user=self.user)
        self.assertEqual(subscription.customer, customer)
        self.assertEqual(subscription.status, UserSubscription.STATUS_PENDING_CARD)
        self.assertEqual(subscription.register_token, "tok_retry")

    @patch("payments.views.FlowClient")
    def test_subscription_status_refreshes_existing_subscription_from_flow(self, flow_client_cls):
        plan = SubscriptionPlan.objects.create(
            flow_plan_id="media-cms-monthly",
            name="Suscripción mensual",
            amount=1200,
            currency="CLP",
            interval=3,
        )
        customer = FlowCustomer.objects.create(
            user=self.user,
            flow_customer_id="cus_123",
            external_id=f"user-{self.user.pk}",
            email=self.user.email,
            name=self.user.name,
        )
        subscription = UserSubscription.objects.create(
            user=self.user,
            customer=customer,
            plan=plan,
            status=UserSubscription.STATUS_PENDING_CARD,
            flow_subscription_id="sus_123",
        )

        flow_client = Mock()
        flow_client.get_subscription.return_value = {
            "subscriptionId": "sus_123",
            "planId": "media-cms-monthly",
            "customerId": "cus_123",
            "status": 1,
            "subscription_start": "2024-01-01 00:00:00",
            "period_start": "2024-01-01 00:00:00",
            "period_end": "2024-01-31 00:00:00",
            "next_invoice_date": "2024-02-01 00:00:00",
            "morose": 0,
            "cancel_at_period_end": 0,
        }
        flow_client_cls.return_value = flow_client

        response = self.client.get(reverse("subscription_status"))

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, UserSubscription.STATUS_ACTIVE)
        self.assertEqual(subscription.flow_status, UserSubscription.FLOW_STATUS_ACTIVE)
        self.assertEqual(subscription.morose, 0)
        self.assertTrue(response.json()["subscription"]["active"])
        flow_client.get_subscription.assert_called_once_with(subscription_id="sus_123")

    @patch("payments.views.FlowClient")
    def test_register_return_creates_active_subscription(self, flow_client_cls):
        plan = SubscriptionPlan.objects.create(
            flow_plan_id="media-cms-monthly",
            name="Suscripción mensual",
            amount=1200,
            currency="CLP",
            interval=3,
        )
        customer = FlowCustomer.objects.create(
            user=self.user,
            flow_customer_id="cus_123",
            external_id=f"user-{self.user.pk}",
            email=self.user.email,
            name=self.user.name,
        )
        subscription = UserSubscription.objects.create(
            user=self.user,
            customer=customer,
            plan=plan,
            status=UserSubscription.STATUS_PENDING_CARD,
            register_token="tok_123",
        )

        flow_client = Mock()
        flow_client.get_customer_register_status.return_value = {
            "status": "1",
            "customerId": "cus_123",
            "creditCardType": "Visa",
            "last4CardDigits": "4425",
            "cardNumber": "457630 **** **** 4425",
            "issuerBank": "BANCO TEST",
        }
        flow_client.create_subscription.return_value = {
            "subscriptionId": "sus_123",
            "planId": "media-cms-monthly",
            "customerId": "cus_123",
            "status": 1,
            "subscription_start": "2024-01-01 00:00:00",
            "period_start": "2024-01-01 00:00:00",
            "period_end": "2024-01-31 00:00:00",
            "next_invoice_date": "2024-02-01 00:00:00",
            "cancel_at_period_end": 0,
        }
        flow_client_cls.return_value = flow_client

        response = self.client.post(reverse("subscription_register_return"), {"token": "tok_123"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("subscription_portal"))

        subscription.refresh_from_db()
        customer.refresh_from_db()
        self.assertEqual(subscription.status, UserSubscription.STATUS_ACTIVE)
        self.assertEqual(subscription.flow_subscription_id, "sus_123")
        self.assertEqual(subscription.register_token, "")
        self.assertEqual(customer.credit_card_type, "Visa")
        self.assertEqual(customer.last4_card_digits, "4425")

    @patch("payments.views.FlowClient")
    def test_update_card_redirects_to_flow_register(self, flow_client_cls):
        plan = SubscriptionPlan.objects.create(
            flow_plan_id="media-cms-monthly",
            name="Suscripción mensual",
            amount=1200,
            currency="CLP",
            interval=3,
        )
        customer = FlowCustomer.objects.create(
            user=self.user,
            flow_customer_id="cus_123",
            external_id=f"user-{self.user.pk}",
            email=self.user.email,
            name=self.user.name,
            credit_card_type="Visa",
            last4_card_digits="1111",
        )
        subscription = UserSubscription.objects.create(
            user=self.user,
            customer=customer,
            plan=plan,
            status=UserSubscription.STATUS_ACTIVE,
            flow_subscription_id="sus_123",
            flow_status=UserSubscription.FLOW_STATUS_ACTIVE,
            morose=0,
        )

        flow_client = Mock()
        flow_client.is_configured.return_value = True
        flow_client.register_customer.return_value = FlowRedirectResult(
            redirect_url="https://flow.test/register?token=tok_card_update",
            token="tok_card_update",
            raw={"url": "https://flow.test/register", "token": "tok_card_update"},
        )
        flow_client_cls.return_value = flow_client

        response = self.client.post(reverse("subscription_update_card"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://flow.test/register?token=tok_card_update")
        flow_client.register_customer.assert_called_once_with(
            customer_id="cus_123",
            url_return="http://testserver" + reverse("subscription_register_return"),
        )
        subscription.refresh_from_db()
        self.assertEqual(subscription.register_token, "tok_card_update")
        self.assertEqual(subscription.status, UserSubscription.STATUS_ACTIVE)

    @patch("payments.views.FlowClient")
    def test_register_return_updates_card_without_creating_duplicate_subscription(self, flow_client_cls):
        plan = SubscriptionPlan.objects.create(
            flow_plan_id="media-cms-monthly",
            name="Suscripción mensual",
            amount=1200,
            currency="CLP",
            interval=3,
        )
        customer = FlowCustomer.objects.create(
            user=self.user,
            flow_customer_id="cus_123",
            external_id=f"user-{self.user.pk}",
            email=self.user.email,
            name=self.user.name,
            credit_card_type="Visa",
            last4_card_digits="1111",
        )
        subscription = UserSubscription.objects.create(
            user=self.user,
            customer=customer,
            plan=plan,
            status=UserSubscription.STATUS_ACTIVE,
            flow_subscription_id="sus_123",
            flow_status=UserSubscription.FLOW_STATUS_ACTIVE,
            morose=0,
            register_token="tok_card_update",
        )

        flow_client = Mock()
        flow_client.get_customer_register_status.return_value = {
            "status": "1",
            "customerId": "cus_123",
            "creditCardType": "Mastercard",
            "last4CardDigits": "9876",
            "cardNumber": "555555 **** **** 9876",
            "issuerBank": "BANCO NUEVO",
        }
        flow_client.get_subscription.return_value = {
            "subscriptionId": "sus_123",
            "planId": "media-cms-monthly",
            "customerId": "cus_123",
            "status": 1,
            "subscription_start": "2024-01-01 00:00:00",
            "period_start": "2024-01-01 00:00:00",
            "period_end": "2024-01-31 00:00:00",
            "next_invoice_date": "2024-02-01 00:00:00",
            "morose": 0,
            "cancel_at_period_end": 0,
        }
        flow_client_cls.return_value = flow_client

        response = self.client.post(reverse("subscription_register_return"), {"token": "tok_card_update"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("subscription_portal"))
        flow_client.create_subscription.assert_not_called()
        flow_client.get_subscription.assert_called_once_with(subscription_id="sus_123")
        subscription.refresh_from_db()
        customer.refresh_from_db()
        self.assertEqual(subscription.register_token, "")
        self.assertEqual(subscription.status, UserSubscription.STATUS_ACTIVE)
        self.assertEqual(customer.credit_card_type, "Mastercard")
        self.assertEqual(customer.last4_card_digits, "9876")

    @patch("payments.views.FlowClient")
    def test_cancel_subscription_updates_status(self, flow_client_cls):
        plan = SubscriptionPlan.objects.create(
            flow_plan_id="media-cms-monthly",
            name="Suscripción mensual",
            amount=1200,
            currency="CLP",
            interval=3,
        )
        customer = FlowCustomer.objects.create(
            user=self.user,
            flow_customer_id="cus_123",
            external_id=f"user-{self.user.pk}",
            email=self.user.email,
            name=self.user.name,
        )
        subscription = UserSubscription.objects.create(
            user=self.user,
            customer=customer,
            plan=plan,
            status=UserSubscription.STATUS_ACTIVE,
            flow_subscription_id="sus_123",
        )

        flow_client = Mock()
        flow_client.cancel_subscription.return_value = {
            "subscriptionId": "sus_123",
            "planId": "media-cms-monthly",
            "customerId": "cus_123",
            "status": 4,
            "cancel_at_period_end": 1,
            "cancel_at": "2024-01-31 00:00:00",
        }
        flow_client_cls.return_value = flow_client

        response = self.client.post(reverse("subscription_cancel"), {"at_period_end": "1"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("subscription_portal"))
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, UserSubscription.STATUS_CANCELED)
        self.assertTrue(subscription.cancel_at_period_end)
