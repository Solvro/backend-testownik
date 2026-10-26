from types import SimpleNamespace

from django.test import RequestFactory, TestCase
from mcp.server.fastmcp.tools import ToolManager

from quizzes.mcp import StudyTools
from quizzes.models import Question, Quiz, QuizSession
from users.mcp import UserTools
from users.models import User, UserSettings


class MCPStatefulReadAnnotationsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="mcp-review@example.com", first_name="Review", last_name="Test")
        self.quiz = Quiz.objects.create(title="Review sample", creator=self.user, folder=self.user.root_folder)
        self.question = Question.objects.create(quiz=self.quiz, order=1, text="Sample question")
        self.request = RequestFactory().get("/api/mcp")
        self.request.user = self.user
        self.request.auth = SimpleNamespace(scope="study:read user:read")

    def assert_published_as_write(self, toolset, name):
        manager = ToolManager()
        tools = {tool.name: tool for tool in toolset._add_tools_to(manager)}
        self.assertFalse(tools[name].annotations.readOnlyHint)
        self.assertFalse(tools[name].annotations.destructiveHint)
        self.assertFalse(tools[name].annotations.openWorldHint)

    def test_session_creation_is_published_as_a_write(self):
        tools = StudyTools(request=self.request)
        self.assertFalse(QuizSession.objects.filter(quiz=self.quiz, user=self.user).exists())
        result = tools.get_quiz_session(str(self.quiz.id))
        self.assertTrue(result["is_new"])
        self.assertTrue(QuizSession.objects.filter(quiz=self.quiz, user=self.user).exists())
        self.assert_published_as_write(tools, "get_quiz_session")

    def test_selecting_a_question_is_published_as_a_write(self):
        tools = StudyTools(request=self.request)
        result = tools.get_next_question(str(self.quiz.id))
        session = QuizSession.objects.get(quiz=self.quiz, user=self.user, is_active=True)
        self.assertEqual(result["id"], str(self.question.id))
        self.assertEqual(session.current_question_id, self.question.id)
        self.assert_published_as_write(tools, "get_next_question")

    def test_default_settings_creation_is_published_as_a_write(self):
        UserSettings.objects.filter(user=self.user).delete()
        tools = UserTools(request=self.request)
        result = tools.get_my_settings()
        self.assertIn("initial_reoccurrences", result)
        self.assertTrue(UserSettings.objects.filter(user=self.user).exists())
        self.assert_published_as_write(tools, "get_my_settings")
