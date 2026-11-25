from django.test import SimpleTestCase
from drf_spectacular.generators import SchemaGenerator


class SchemaTagTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.schema = SchemaGenerator().get_schema(request=None, public=True)

    def _tags(self, path, method):
        return self.schema["paths"][path][method]["tags"]

    def test_no_operation_falls_back_to_the_api_prefix_tag(self):
        tags = {tag for operations in self.schema["paths"].values() for op in operations.values() for tag in op["tags"]}

        self.assertNotIn("api", tags)

    def test_operations_are_tagged_by_their_first_segment_after_api(self):
        self.assertEqual(self._tags("/api/ai/chats/", "get"), ["ai"])
        self.assertEqual(self._tags("/api/quizzes/", "get"), ["quizzes"])
        self.assertEqual(self._tags("/api/oauth/authorize/request/", "get"), ["oauth"])

    def test_well_known_keeps_its_own_group(self):
        self.assertEqual(self._tags("/.well-known/oauth-authorization-server", "get"), [".well-known"])

    def test_explicit_view_tags_still_win(self):
        self.assertEqual(self._tags("/api/login/", "get"), ["Authentication"])
        self.assertEqual(self._tags("/api/upload/", "post"), ["uploads"])
