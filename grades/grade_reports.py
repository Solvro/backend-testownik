from datetime import date, datetime
from typing import TypedDict

from usos_api.models import (
    ExamReport,
    ExamReportCourseUnit,
    ExamReportGradeDistributionItem,
    ExamReportIssuerGrade,
    ExamReportSession,
    LangDict,
    User,
    UserExamReportsByTerm,
)

from users.models import CourseClassType

GRADE_REPORT_FIELDS = [
    "course[id|name]",
    "course_unit[classtype_id|course_id|course_name|id|term_id]",
    "counts_into_average",
    "grades_distribution",
    "id",
    "sessions[issuer_grades[comment|counts_into_average|date_modified|modification_author|passes|value_symbol]|number]",
    "term_id",
    "type_description",
    "type_id",
]


class SerializedClassType(TypedDict):
    id: str
    name_pl: str | None
    name_en: str | None


class SerializedModificationAuthor(TypedDict, total=False):
    id: str | int | None
    first_name: str | None
    last_name: str | None


class SerializedLangDict(TypedDict, total=False):
    pl: str | None
    en: str | None


class SerializedCourseUnit(TypedDict):
    id: str | None
    course_id: str | None
    course_name: SerializedLangDict | None
    classtype_id: str | None
    term_id: str | None


class SerializedGradeDistributionItem(TypedDict):
    grade_symbol: str | None
    percentage: float | None


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
    modification_author: SerializedModificationAuthor | None


class SerializedReport(TypedDict):
    id: str | int | None
    type_id: str | None
    type_description: str | None
    scope: str
    class_type_id: str | None
    class_type: SerializedClassType | None
    course_unit: SerializedCourseUnit | None
    grades_distribution: list[SerializedGradeDistributionItem]
    grades: list[SerializedGrade]


class SerializedCourse(TypedDict):
    course_id: str
    course_name: str
    term_id: str
    ects: float
    weighted_average: float | None
    passing_status: str
    class_types: list[SerializedClassType]
    reports: list[SerializedReport]


class TermStats(TypedDict):
    weighted_average: float | None
    weighted_ects: float
    weighted_points: float


class SerializedCoursesResult(TypedDict):
    courses: list[SerializedCourse]
    grades_by_term: dict[str, list[SerializedGrade]]


COURSE_GROUP_CLASS_TYPE: SerializedClassType = {
    "id": "G",
    "name_pl": "Grupa kursów",
    "name_en": "Course group",
}


def lang_text(value: LangDict | dict[str, str | None] | str | None, lang: str = "pl") -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get(lang) or value.get("en") or value.get("pl")
    return getattr(value, lang, None) or value.en or value.pl


def lang_payload(value: LangDict | dict[str, str | None] | None) -> SerializedLangDict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        payload: SerializedLangDict = {"pl": value.get("pl"), "en": value.get("en")}
        return payload
    payload: SerializedLangDict = {"pl": value.pl, "en": value.en}
    return payload


def serialize_class_type(
    class_type_id: str | None,
    class_types_by_id: dict[str, CourseClassType],
) -> SerializedClassType | None:
    if not class_type_id:
        return None
    class_type = class_types_by_id.get(class_type_id)
    payload: SerializedClassType = {
        "id": class_type_id,
        "name_pl": class_type.name_pl if class_type else None,
        "name_en": class_type.name_en if class_type else None,
    }
    return payload


def course_class_type_from_suffix(
    course_id: str,
    class_types_by_id: dict[str, CourseClassType],
) -> SerializedClassType | None:
    if not course_id:
        return None

    suffix = course_id[-1].upper()
    if suffix == COURSE_GROUP_CLASS_TYPE["id"]:
        return COURSE_GROUP_CLASS_TYPE
    if suffix not in class_types_by_id:
        return None

    return serialize_class_type(suffix, class_types_by_id)


def numeric_grade(value_symbol: str | None) -> float | None:
    if value_symbol is None:
        return None
    try:
        return float(value_symbol.replace(",", "."))
    except ValueError:
        return None


def date_text(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return value


def serialize_user(value: User | None) -> SerializedModificationAuthor | None:
    if value is None:
        return None

    payload: SerializedModificationAuthor = {
        "id": value.id,
        "first_name": value.first_name,
        "last_name": value.last_name,
    }
    return payload


def serialize_course_unit(course_unit: ExamReportCourseUnit | None) -> SerializedCourseUnit | None:
    if course_unit is None:
        return None

    payload: SerializedCourseUnit = {
        "id": course_unit.id,
        "course_id": course_unit.course_id,
        "course_name": lang_payload(course_unit.course_name),
        "classtype_id": course_unit.classtype_id,
        "term_id": course_unit.term_id,
    }
    return payload


def serialize_distribution_item(
    item: ExamReportGradeDistributionItem,
) -> SerializedGradeDistributionItem:
    return {
        "grade_symbol": item.grade_symbol,
        "percentage": item.percentage,
    }


def issuer_grades(session: ExamReportSession) -> list[ExamReportIssuerGrade]:
    return session.issuer_grades or []


def counts_into_average(report: ExamReport, grade: ExamReportIssuerGrade) -> bool:
    if grade.counts_into_average is not None:
        return bool(grade.counts_into_average)
    if report.counts_into_average is not None:
        return bool(report.counts_into_average)
    return True


def course_name_from_reports(reports: list[ExamReport]) -> str | None:
    for report in reports:
        course_name = lang_text(report.course.name if report.course is not None else None)
        if course_name:
            return course_name

        course_unit_name = lang_text(report.course_unit.course_name if report.course_unit is not None else None)
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
    course_unit = report.course_unit
    value_symbol = grade.value_symbol
    scope = "course_unit" if course_unit else "course"

    return {
        "term_id": term_id,
        "course_id": course_id,
        "course_name": course_name,
        "ects": ects,
        "value": numeric_grade(value_symbol),
        "value_symbol": value_symbol,
        "value_description": lang_text(grade.value_description) or value_symbol,
        "counts_into_average": counts_into_average(report, grade),
        "passes": grade.passes or False,
        "exam_id": report.id,
        "exam_session_number": session.number,
        "report_type_id": report.type_id,
        "report_type_description": lang_text(report.type_description),
        "scope": scope,
        "course_unit_id": course_unit.id if course_unit else None,
        "class_type_id": class_type_id,
        "class_type": serialize_class_type(class_type_id, class_types_by_id),
        "comment": grade.comment,
        "date_modified": date_text(grade.date_modified),
        "modification_author": serialize_user(grade.modification_author),
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
        for session in (report.sessions or [])
        for grade in issuer_grades(session)
    ]


def weighted_totals(grades: list[SerializedGrade]) -> tuple[float | None, float, float]:
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
        course_unit = report.course_unit
        scope = "course_unit" if course_unit else "course"
        class_type_id = course_unit.classtype_id if course_unit else None
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

        report_payload: SerializedReport = {
            "id": report.id,
            "type_id": report.type_id,
            "type_description": lang_text(report.type_description),
            "scope": scope,
            "class_type_id": class_type_id,
            "class_type": serialize_class_type(class_type_id, class_types_by_id),
            "course_unit": serialize_course_unit(course_unit),
            "grades_distribution": [serialize_distribution_item(item) for item in (report.grades_distribution or [])],
            "grades": grades,
        }
        report_payloads.append(report_payload)

    weighted_average, _, _ = weighted_totals(final_grades)
    course_class_type = course_class_type_from_suffix(course_id, class_types_by_id)
    class_types: list[SerializedClassType] = [] if course_class_type is None else [course_class_type]
    course_payload: SerializedCourse = {
        "course_id": course_id,
        "course_name": course_name,
        "term_id": term_id,
        "ects": ects or 0,
        "weighted_average": weighted_average,
        "passing_status": passing_status(final_grades),
        "class_types": class_types,
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
