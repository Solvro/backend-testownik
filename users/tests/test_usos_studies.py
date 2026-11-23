from types import SimpleNamespace
from unittest.mock import AsyncMock

from django.test import SimpleTestCase, TestCase
from usos_api import models as usos

from users.models import Faculty, StudentProgramme, StudyProgramme, User
from users.serializers import PublicUserSerializer, UserSerializer
from users.usos_studies import parse_semester, select_programmes, sync_user_studies


def stage(description):
    return usos.ProgrammeStage(description=usos.LangDict(pl=description))


def student_programme(programme_id="W04-ITEP", status="active", is_primary=True, stages=None):
    return usos.StudentProgramme(
        status=status,
        is_primary=is_primary,
        stages=[stage("7 semestr, informatyka techniczna")] if stages is None else stages,
        programme=usos.Programme(
            id=programme_id,
            name=usos.LangDict(pl="informatyka techniczna, pierwszego stopnia, stacjonarne"),
            faculty=usos.Faculty(id="W4N", name=usos.LangDict(pl="Wydział Informatyki i Telekomunikacji")),
        ),
    )


def usos_client(**get_kwargs):
    return SimpleNamespace(programme_service=SimpleNamespace(get_student_programmes=AsyncMock(**get_kwargs)))


def programme_ids(selected):
    return [item.programme.id for item in selected]


class ParseSemesterTests(SimpleTestCase):
    def test_reads_the_number_from_the_description(self):
        self.assertEqual(parse_semester([stage("7 semestr, informatyka techniczna")]), 7)

    def test_same_semester_in_several_stages_is_kept(self):
        self.assertEqual(parse_semester([stage("3 semestr, a"), stage("3 semestr, b")]), 3)

    def test_different_semesters_leave_it_unknown(self):
        self.assertIsNone(parse_semester([stage("3 semestr, a"), stage("4 semestr, b")]))

    def test_unreadable_or_missing_stages_leave_it_unknown(self):
        self.assertIsNone(parse_semester([stage("rok 2, grupa A")]))
        self.assertIsNone(parse_semester([usos.ProgrammeStage()]))
        self.assertIsNone(parse_semester([]))
        self.assertIsNone(parse_semester(None))


class SelectProgrammesTests(SimpleTestCase):
    def test_puts_the_primary_programme_first(self):
        selected = select_programmes([student_programme("A", is_primary=False), student_programme("B")])
        self.assertEqual(programme_ids(selected), ["B", "A"])

    def test_order_is_stable_without_a_primary_programme(self):
        first = student_programme("A", is_primary=False)
        second = student_programme("B", is_primary=False)
        self.assertEqual(programme_ids(select_programmes([second, first])), ["A", "B"])

    def test_repeated_programme_is_returned_once(self):
        selected = select_programmes([student_programme("A", is_primary=False), student_programme("A")])
        self.assertEqual(programme_ids(selected), ["A"])
        self.assertTrue(selected[0].is_primary)

    def test_ignores_programmes_the_student_no_longer_attends(self):
        self.assertEqual(select_programmes([student_programme(status="graduated_before_diploma")]), [])


class SyncUserStudiesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="student@student.pwr.edu.pl")

    async def stored(self):
        return [
            (item.programme_id, item.semester, item.is_primary)
            async for item in StudentProgramme.objects.filter(user=self.user)
        ]

    async def test_stores_the_faculty_programme_and_semester(self):
        await sync_user_studies(usos_client(return_value=[student_programme()]), self.user)

        self.assertEqual(await self.stored(), [("W04-ITEP", 7, True)])
        programme = await StudyProgramme.objects.select_related("faculty").aget(pk="W04-ITEP")
        self.assertEqual(programme.faculty.name, "Wydział Informatyki i Telekomunikacji")

    async def test_stores_every_active_programme_with_its_own_semester(self):
        programmes = [
            student_programme("MAT", is_primary=False, stages=[stage("3 semestr, matematyka")]),
            student_programme("ITE"),
        ]

        await sync_user_studies(usos_client(return_value=programmes), self.user)

        self.assertEqual(await self.stored(), [("ITE", 7, True), ("MAT", 3, False)])

    async def test_marks_one_primary_when_usos_marks_several(self):
        programmes = [student_programme("A"), student_programme("B")]

        await sync_user_studies(usos_client(return_value=programmes), self.user)

        self.assertEqual(await self.stored(), [("A", 7, True), ("B", 7, False)])

    async def test_removes_programmes_the_student_left(self):
        programmes = [student_programme("ITE"), student_programme("MAT", is_primary=False)]
        await sync_user_studies(usos_client(return_value=programmes), self.user)

        await sync_user_studies(usos_client(return_value=[student_programme("ITE")]), self.user)

        self.assertEqual(await self.stored(), [("ITE", 7, True)])

    async def test_clears_the_studies_when_no_programme_is_active(self):
        await sync_user_studies(usos_client(return_value=[student_programme()]), self.user)

        await sync_user_studies(usos_client(return_value=[]), self.user)

        self.assertEqual(await self.stored(), [])

    async def test_usos_failure_keeps_the_stored_studies_without_raising(self):
        await sync_user_studies(usos_client(return_value=[student_programme()]), self.user)

        with self.assertLogs("users.usos_studies", level="WARNING"):
            await sync_user_studies(usos_client(side_effect=RuntimeError("USOS down")), self.user)

        self.assertEqual(await self.stored(), [("W04-ITEP", 7, True)])

    async def test_programme_without_a_faculty_is_stored(self):
        data = student_programme()
        data.programme.faculty = None

        await sync_user_studies(usos_client(return_value=[data]), self.user)

        programme = await StudyProgramme.objects.aget(pk="W04-ITEP")
        self.assertIsNone(programme.faculty_id)
        self.assertFalse(await Faculty.objects.aexists())


class StudiesPrivacyTests(SimpleTestCase):
    def test_studies_are_not_exposed_by_the_api(self):
        for serializer in (UserSerializer, PublicUserSerializer):
            self.assertNotIn("student_programmes", serializer.Meta.fields)
