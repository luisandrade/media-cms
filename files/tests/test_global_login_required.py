from django.test import Client, TestCase, override_settings


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
