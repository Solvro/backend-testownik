from constance.test import override_config
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()
URL = "/api/wrapped/global/"


@override_config(WRAPPED_ENABLED=True)
class GlobalWrappedAccessTests(APITestCase):
    def test_anonymous_visitors_are_refused(self):
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_regular_users_are_refused(self):
        self.client.force_authenticate(User.objects.create_user(email="user@example.com"))
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_open_it(self):
        self.client.force_authenticate(User.objects.create_user(email="staff@example.com", is_staff=True))
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_200_OK)
