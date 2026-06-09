from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from files.tests import create_account
from payments.models import FlowCustomer, SubscriptionPlan, UserSubscription
from users.adapter import MyAccountAdapter


class TestMyAccountAdapter(TestCase):
	fixtures = ["fixtures/categories.json", "fixtures/encoding_profiles.json"]

	def setUp(self):
		self.factory = RequestFactory()
		self.adapter = MyAccountAdapter()

	def test_superuser_redirects_to_statistics_dashboard(self):
		request = self.factory.get("/accounts/login/")
		request.user = create_account(is_superuser=True)

		redirect_url = self.adapter.get_login_redirect_url(request)

		self.assertEqual(redirect_url, reverse("manage_statistics"))

	@override_settings(LOGIN_REDIRECT_URL="/custom-home/", FLOW_SUBSCRIPTION_ENABLED=False)
	def test_non_superuser_uses_default_login_redirect(self):
		request = self.factory.get("/accounts/login/")
		request.user = create_account()

		redirect_url = self.adapter.get_login_redirect_url(request)

		self.assertEqual(redirect_url, "/custom-home/")

	@override_settings(
		FLOW_SUBSCRIPTION_ENABLED=True,
		FLOW_SUBSCRIPTION_PLAN_ID="media-cms-monthly",
		LOGIN_REDIRECT_URL="/custom-home/",
	)
	def test_non_superuser_without_subscription_redirects_to_subscription_portal(self):
		request = self.factory.get("/accounts/login/")
		request.user = create_account()

		redirect_url = self.adapter.get_login_redirect_url(request)

		self.assertEqual(redirect_url, reverse("subscription_portal"))

	@override_settings(
		FLOW_SUBSCRIPTION_ENABLED=True,
		FLOW_SUBSCRIPTION_PLAN_ID="media-cms-monthly",
		LOGIN_REDIRECT_URL="/custom-home/",
	)
	def test_non_superuser_with_active_subscription_keeps_default_redirect(self):
		request = self.factory.get("/accounts/login/")
		request.user = create_account()
		plan = SubscriptionPlan.objects.create(
			flow_plan_id="media-cms-monthly",
			name="Suscripción mensual",
			amount=1200,
			currency="CLP",
			interval=3,
		)
		customer = FlowCustomer.objects.create(
			user=request.user,
			flow_customer_id="cus_test",
			external_id=f"user-{request.user.pk}",
			email=request.user.email,
			name=request.user.name,
		)
		UserSubscription.objects.create(
			user=request.user,
			customer=customer,
			plan=plan,
			status=UserSubscription.STATUS_ACTIVE,
			flow_subscription_id="sus_test",
		)

		redirect_url = self.adapter.get_login_redirect_url(request)

		self.assertEqual(redirect_url, "/custom-home/")

	def test_superuser_respects_next_parameter(self):
		request = self.factory.get("/accounts/login/", {"next": "/requested-path/"})
		request.user = create_account(is_superuser=True)

		redirect_url = self.adapter.get_login_redirect_url(request)

		self.assertEqual(redirect_url, "/requested-path/")

	def test_superuser_ignores_root_next_redirect(self):
		request = self.factory.get("/accounts/login/", {"next": "/"})
		request.user = create_account(is_superuser=True)

		redirect_url = self.adapter.get_login_redirect_url(request)

		self.assertEqual(redirect_url, reverse("manage_statistics"))


class TestAccountLoginView(TestCase):
	fixtures = ["fixtures/categories.json", "fixtures/encoding_profiles.json"]

	def setUp(self):
		self.client = Client()
		self.password = "pass1234"

	def test_superuser_root_next_redirects_to_statistics_dashboard(self):
		user = create_account(username="super-login", password=self.password, is_superuser=True)

		response = self.client.post(
			"/accounts/login/?next=/",
			{"login": user.username, "password": self.password},
			follow=False,
		)

		self.assertEqual(response.status_code, 302)
		self.assertEqual(response["Location"], reverse("manage_statistics"))

	def test_superuser_keeps_non_root_next_redirect(self):
		user = create_account(username="super-next", password=self.password, is_superuser=True)

		response = self.client.post(
			"/accounts/login/?next=/requested-path/",
			{"login": user.username, "password": self.password},
			follow=False,
		)

		self.assertEqual(response.status_code, 302)
		self.assertEqual(response["Location"], "/requested-path/")


class TestManageUsersApi(TestCase):
	fixtures = ["fixtures/categories.json", "fixtures/encoding_profiles.json"]

	def setUp(self):
		self.client = Client()
		self.manager = create_account(username="manager-users", is_manager=True)
		self.user = create_account(username="listed-user")

	def test_manage_users_endpoint_returns_200(self):
		self.client.force_login(self.manager)

		response = self.client.get("/api/v1/manage_users")

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertIn("results", payload)
		self.assertTrue(any(item["username"] == self.user.username for item in payload["results"]))
