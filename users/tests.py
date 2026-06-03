from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from files.tests import create_account
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

	@override_settings(LOGIN_REDIRECT_URL="/custom-home/")
	def test_non_superuser_uses_default_login_redirect(self):
		request = self.factory.get("/accounts/login/")
		request.user = create_account()

		redirect_url = self.adapter.get_login_redirect_url(request)

		self.assertEqual(redirect_url, "/custom-home/")

	def test_superuser_respects_next_parameter(self):
		request = self.factory.get("/accounts/login/", {"next": "/requested-path/"})
		request.user = create_account(is_superuser=True)

		redirect_url = self.adapter.get_login_redirect_url(request)

		self.assertEqual(redirect_url, "/requested-path/")
