from rest_framework.test import APITestCase

from users.models import AccountType, User


class UserSearchTests(APITestCase):
    url = "/api/users/"

    def setUp(self):
        self.searcher = User.objects.create_user(
            email="searcher@example.com", first_name="Ewa", last_name="Szukająca", account_type=AccountType.STUDENT
        )
        self.visible = User.objects.create_user(
            email="visible@example.com",
            first_name="Jan",
            last_name="Kowalski",
            student_number="123456",
            account_type=AccountType.STUDENT,
        )
        self.hidden = User.objects.create_user(
            email="hidden@example.com",
            first_name="Anna",
            last_name="Ukryta",
            student_number="654321",
            account_type=AccountType.STUDENT,
            hide_profile=True,
        )
        self.client.force_authenticate(self.searcher)

    def search(self, query):
        return self.client.get(self.url, {"search": query})

    def result_ids(self, response):
        return {item["id"] for item in response.data}

    def test_results_do_not_expose_student_number(self):
        response = self.search("Kowalski")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.result_ids(response), {str(self.visible.id)})
        self.assertNotIn("student_number", response.data[0])

    def test_hidden_profile_is_excluded_from_three_word_search(self):
        response = self.search("Anna Ukryta 654321")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_hidden_profile_is_still_found_by_exact_student_number(self):
        response = self.search("654321")

        self.assertEqual(self.result_ids(response), {str(self.hidden.id)})

    def test_guests_cannot_search(self):
        self.client.force_authenticate(User.objects.create_guest_user())

        response = self.search("Kowalski")

        self.assertEqual(response.status_code, 403)
