from django.contrib.admin.sites import AdminSite
from django.contrib.admin.utils import flatten_fieldsets
from django.test import RequestFactory, SimpleTestCase

from users.admin import UserAdmin
from users.models import User


class UserAdminPhotoUrlTests(SimpleTestCase):
    def test_photo_url_is_visible_but_not_editable(self):
        request = RequestFactory().get("/api/admin/users/user/")
        request.user = User(is_staff=True, is_superuser=True)
        user = User(email="photo-admin@example.com", photo_url="https://example.com/original.jpg")
        user_admin = UserAdmin(User, AdminSite())

        self.assertIn("photo_url", flatten_fieldsets(user_admin.get_fieldsets(request, user)))
        self.assertIn("photo_url", user_admin.get_readonly_fields(request, user))
        self.assertNotIn("photo_url", user_admin.get_form(request, user).base_fields)
