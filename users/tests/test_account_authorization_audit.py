"""Disposable account privacy and mutation authorization regressions."""

import itertools
import json

from django.test import TestCase
from rest_framework.test import APIClient

from users.models import AccountLevel, AccountType, User, UserSettings


class AccountAuthorizationAuditTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(
            email="account-audit-actor@example.invalid", account_type=AccountType.EMAIL
        )
        self.hidden = User.objects.create_user(
            email="account-audit-hidden@example.invalid",
            first_name="SyntheticHidden",
            last_name="PrivacyFixture",
            student_number="987654",
            account_type=AccountType.STUDENT,
            hide_profile=True,
        )
        self.visible = User.objects.create_user(
            email="account-audit-visible@example.invalid",
            first_name="SyntheticVisible",
            last_name="PublicFixture",
            student_number="123456",
            account_type=AccountType.STUDENT,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.actor)

    def search(self, text):
        response = self.client.get("/api/users/", {"search": text})
        self.assertEqual(response.status_code, 200)
        entries = response.data.get("results", []) if isinstance(response.data, dict) else response.data
        return {str(entry["id"]) for entry in entries}

    def test_hidden_profile_cannot_be_found_by_partial_name_and_partial_index(self):
        for tokens in (
            ("SyntheticHidden", "PrivacyFixture", "987"),
            ("Syn", "Pri", "987"),
            ("SyntheticHidden", "PrivacyFixture", "987654"),
        ):
            for terms in itertools.permutations(tokens):
                with self.subTest(terms=terms):
                    self.assertNotIn(str(self.hidden.pk), self.search(" ".join(terms)))

    def test_hidden_name_search_is_blocked(self):
        for query in (
            "SyntheticHidden",
            "PrivacyFixture",
            "SyntheticHidden PrivacyFixture",
            "SyntheticHidden  PrivacyFixture",
            "Syn  Pri",
            "987",
        ):
            with self.subTest(query=query):
                self.assertNotIn(str(self.hidden.pk), self.search(query))

    def test_hidden_exact_student_number_lookup_is_supported(self):
        self.assertIn(str(self.hidden.pk), self.search("987654"))

    def test_visible_three_term_partial_search_is_supported(self):
        self.assertIn(str(self.visible.pk), self.search("SyntheticVisible PublicFixture 123"))

    def test_user_endpoint_does_not_allow_unfiltered_enumeration(self):
        self.assertEqual(self.search(""), set())
        self.assertEqual(self.client.get(f"/api/users/{self.hidden.pk}/").status_code, 404)

    def test_profile_cannot_change_authority_or_other_identity_fields(self):
        payloads = (
            {"account_type": AccountType.LECTURER},
            {"account_level": AccountLevel.GOLD},
            {"is_staff": True},
            {"is_superuser": True},
            {"student_number": "987654"},
            {"email": self.hidden.email},
            {"id": str(self.hidden.pk)},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.client.patch("/api/user/", payload, format="json")
                self.assertEqual(response.status_code, 400)
        self.actor.refresh_from_db()
        self.assertEqual(self.actor.account_type, AccountType.EMAIL)
        self.assertEqual(self.actor.account_level, AccountLevel.BASIC)
        self.assertFalse(self.actor.is_staff)
        self.assertFalse(self.actor.is_superuser)
        self.assertEqual(self.actor.email, "account-audit-actor@example.invalid")
        self.assertNotEqual(self.actor.student_number, "987654")

    def test_settings_cannot_retarget_another_users_row(self):
        other = UserSettings.objects.create(user=self.hidden, notify_marketing=True)
        response = self.client.patch(
            "/api/settings/", {"user": str(self.hidden.pk), "notify_marketing": False}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        other.refresh_from_db()
        self.assertTrue(other.notify_marketing)
        self.assertFalse(UserSettings.objects.get(user=self.actor).notify_marketing)

    def test_non_object_profile_bodies_are_client_errors(self):
        self.client.raise_request_exception = False
        for body in (None, 42, True, "hide_profile", [], ["hide_profile"], [{"hide_profile": True}]):
            with self.subTest(body=body):
                response = self.client.patch("/api/user/", json.dumps(body), content_type="application/json")
                self.assertEqual(response.status_code, 400)
        self.actor.refresh_from_db()
        self.assertFalse(self.actor.hide_profile)
