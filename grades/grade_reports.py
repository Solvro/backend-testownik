from typing import NotRequired, TypedDict

from usos_api.services.exam_reports import (
    ExamReport,
    ExamReportCourseUnit,
    ExamReportGradeDistributionItem,
    ExamReportIssuerGrade,
    ExamReportSession,
    LangDictData,
    UserExamReportsByTerm,
)

from users.models import CourseClassType

GRADE_REPORT_FIELDS = [
    "course[id|name]",
    "course_unit[classtype_id|course_id|course_name|id|term_id]",
    "counts_into_average",
    "grades_distribution",
    "id",
    "sessions[issuer_grades[comment|counts_into_average|date_acquisition|date_modified|modification_author|passes|value_symbol]|number]",
    "term_id",
    "type_description",
    "type_id",
]


class SerializedClassType(TypedDict):
    id: str
    name_pl: str | None
    name_en: str | None


class SerializedGrade(TypedDict):
    term_id: str
    course_id: str
    course_name: str | None
    ects: float | None
    value: float | None
    value_symbol: str | None
    value_description: str | None
    counts_into_average: bool
    passes: bool
    exam_id: str | int | None
    exam_session_number: int | None
    report_type_id: str | None
    report_type_description: str | None
    scope: str
    course_unit_id: str | None
    class_type_id: str | None
    class_type: SerializedClassType | None
    comment: str | None
    date_modified: str | None
    date_acquisition: str | None
    modification_author: str | int | None


class SerializedReport(TypedDict):
    id: str | int | None
    type_id: str | None
    type_description: str | None
    scope: str
    class_type_id: str | None
    class_type: SerializedClassType | None
    course_unit: ExamReportCourseUnit | None
    grades_distribution: list[ExamReportGradeDistributionItem]
    grades: list[SerializedGrade]


class SerializedCourse(TypedDict):
    course_id: str
    course_name: str
    term_id: str
    ects: float
    weighted_average: float | None
    passing_status: str
    reports: list[SerializedReport]


class TermStats(TypedDict):
    weighted_average: float | None
    weighted_ects: float
    weighted_points: float


class SerializedCoursesResult(TypedDict):
    courses: list[SerializedCourse]
    grades_by_term: dict[str, list[SerializedGrade]]


class WeightedGrade(TypedDict):
    counts_into_average: bool
    value: NotRequired[float | None]
    ects: float | None


def lang_text(value: LangDictData | None, lang: str = "pl") -> str | None:
    if value is None:
        return None
    return value.get(lang) or value.get("en") or value.get("pl")


def serialize_class_type(
    class_type_id: str | None,
    class_types_by_id: dict[str, CourseClassType],
) -> SerializedClassType | None:
    if not class_type_id:
        return None
    class_type = class_types_by_id.get(class_type_id)
    return {
        "id": class_type_id,
        "name_pl": class_type.name_pl if class_type else None,
        "name_en": class_type.name_en if class_type else None,
    }


def numeric_grade(value_symbol: str | None) -> float | None:
    if value_symbol is None:
        return None
    try:
        return float(value_symbol.replace(",", "."))
    except ValueError:
        return None


def issuer_grades(session: ExamReportSession) -> list[ExamReportIssuerGrade]:
    grade = session.get("issuer_grades")
    if grade is None:
        return []
    if isinstance(grade, list):
        return grade
    return [grade]


def course_name_from_reports(reports: list[ExamReport]) -> str | None:
    for report in reports:
        course_name = lang_text(report.get("course", {}).get("name"))
        if course_name:
            return course_name

        course_unit_name = lang_text((report.get("course_unit") or {}).get("course_name"))
        if course_unit_name:
            return course_unit_name

    return None


def passing_status(grades: list[SerializedGrade]) -> str:
    counted_grades = [grade for grade in grades if grade["counts_into_average"]]
    if not counted_grades:
        return "not_yet_passed"
    if any(grade["passes"] for grade in counted_grades):
        return "passed"
    return "failed"


def serialize_grade(
    *,
    term_id: str,
    course_id: str,
    course_name: str | None,
    ects: float | None,
    report: ExamReport,
    session: ExamReportSession,
    grade: ExamReportIssuerGrade,
    class_type_id: str | None,
    class_types_by_id: dict[str, CourseClassType],
) -> SerializedGrade:
    course_unit = report.get("course_unit")
    value_symbol = grade.get("value_symbol")
    scope = "course_unit" if course_unit else "course"

    return {
        "term_id": term_id,
        "course_id": course_id,
        "course_name": course_name,
        "ects": ects,
        "value": numeric_grade(value_symbol),
        "value_symbol": value_symbol,
        "value_description": value_symbol,
        "counts_into_average": grade.get("counts_into_average", report.get("counts_into_average", True)),
        "passes": grade.get("passes", False),
        "exam_id": report.get("id"),
        "exam_session_number": session.get("number"),
        "report_type_id": report.get("type_id"),
        "report_type_description": lang_text(report.get("type_description")),
        "scope": scope,
        "course_unit_id": course_unit.get("id") if course_unit else None,
        "class_type_id": class_type_id,
        "class_type": serialize_class_type(class_type_id, class_types_by_id),
        "comment": grade.get("comment"),
        "date_modified": grade.get("date_modified"),
        "date_acquisition": grade.get("date_acquisition"),
        "modification_author": grade.get("modification_author"),
    }


def serialize_report_grades(
    *,
    term_id: str,
    course_id: str,
    course_name: str | None,
    ects: float | None,
    report: ExamReport,
    class_type_id: str | None,
    class_types_by_id: dict[str, CourseClassType],
) -> list[SerializedGrade]:
    return [
        serialize_grade(
            term_id=term_id,
            course_id=course_id,
            course_name=course_name,
            ects=ects,
            report=report,
            session=session,
            grade=grade,
            class_type_id=class_type_id,
            class_types_by_id=class_types_by_id,
        )
        for session in report.get("sessions", [])
        for grade in issuer_grades(session)
    ]


def weighted_totals(grades: list[WeightedGrade]) -> tuple[float | None, float, float]:
    numeric_weighted_grades = [
        grade
        for grade in grades
        if grade["counts_into_average"] and grade.get("value") is not None and grade["ects"] is not None
    ]
    numeric_weighted_ects = sum(grade["ects"] or 0.0 for grade in numeric_weighted_grades)
    weighted_ects = sum(grade["ects"] or 0.0 for grade in grades if grade["counts_into_average"])
    weighted_points = sum(
        (grade.get("value") or 0.0) * (grade["ects"] or 0.0)
        for grade in grades
        if grade["counts_into_average"] and grade.get("value") is not None
    )
    if not numeric_weighted_ects:
        return None, weighted_ects, weighted_points
    return weighted_points / numeric_weighted_ects, weighted_ects, weighted_points


def serialize_course(
    term_id: str,
    course_id: str,
    reports: list[ExamReport],
    ects: float | None,
    class_types_by_id: dict[str, CourseClassType],
) -> tuple[SerializedCourse, list[SerializedGrade]]:
    course_name = course_name_from_reports(reports) or course_id
    report_payloads: list[SerializedReport] = []
    final_grades: list[SerializedGrade] = []

    for report in reports:
        course_unit = report.get("course_unit")
        scope = "course_unit" if course_unit else "course"
        class_type_id = course_unit.get("classtype_id") if course_unit else None
        grades = serialize_report_grades(
            term_id=term_id,
            course_id=course_id,
            course_name=course_name,
            ects=ects,
            report=report,
            class_type_id=class_type_id,
            class_types_by_id=class_types_by_id,
        )
        if scope == "course":
            final_grades.extend(grades)

        report_payloads.append(
            {
                "id": report.get("id"),
                "type_id": report.get("type_id"),
                "type_description": lang_text(report.get("type_description")),
                "scope": scope,
                "class_type_id": class_type_id,
                "class_type": serialize_class_type(class_type_id, class_types_by_id),
                "course_unit": course_unit,
                "grades_distribution": report.get("grades_distribution", []),
                "grades": grades,
            }
        )

    weighted_average, _, _ = weighted_totals(final_grades)
    course_payload: SerializedCourse = {
        "course_id": course_id,
        "course_name": course_name,
        "term_id": term_id,
        "ects": ects or 0,
        "weighted_average": weighted_average,
        "passing_status": passing_status(final_grades),
        "reports": report_payloads,
    }
    return course_payload, final_grades


def term_stats(grades: list[SerializedGrade]) -> TermStats:
    weighted_average, weighted_ects, weighted_points = weighted_totals(grades)
    return {
        "weighted_average": weighted_average,
        "weighted_ects": weighted_ects,
        "weighted_points": weighted_points,
    }


def serialize_courses(
    *,
    reports_by_term: UserExamReportsByTerm,
    ects_by_term: dict[str, dict[str, float | None]],
    term_ids: list[str],
    class_types_by_id: dict[str, CourseClassType],
) -> SerializedCoursesResult:
    courses_payload: list[SerializedCourse] = []
    grades_by_term: dict[str, list[SerializedGrade]] = {term_id: [] for term_id in term_ids}

    for report_term_id, courses in reports_by_term.items():
        for course_id, reports in courses.items():
            course_payload, final_grades = serialize_course(
                term_id=report_term_id,
                course_id=course_id,
                reports=reports,
                ects=ects_by_term.get(report_term_id, {}).get(course_id),
                class_types_by_id=class_types_by_id,
            )
            courses_payload.append(course_payload)
            grades_by_term.setdefault(report_term_id, []).extend(final_grades)

    return {"courses": courses_payload, "grades_by_term": grades_by_term}
