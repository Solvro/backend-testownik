from django.test import SimpleTestCase

from grades.grade_reports import passing_status


def grade(*, counts: bool, passes: bool):
    return {"counts_into_average": counts, "passes": passes}


class PassingStatusTests(SimpleTestCase):
    def test_counted_grades_decide_the_status(self):
        self.assertEqual(passing_status([grade(counts=True, passes=True)]), "passed")
        self.assertEqual(passing_status([grade(counts=True, passes=False)]), "failed")

    def test_pass_fail_course_outside_the_average_is_passed(self):
        self.assertEqual(passing_status([grade(counts=False, passes=True)]), "passed")

    def test_course_without_a_passing_grade_is_not_yet_passed(self):
        self.assertEqual(passing_status([]), "not_yet_passed")
        self.assertEqual(passing_status([grade(counts=False, passes=False)]), "not_yet_passed")
