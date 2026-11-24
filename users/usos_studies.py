import logging
import re

from asgiref.sync import sync_to_async
from django.db import transaction
from usos_api import models as usos

from users.models import Faculty, StudentProgramme, StudyProgramme, User

logger = logging.getLogger(__name__)

STUDENT_PROGRAMME_FIELDS = ["status", "is_primary", "stages", "programme[id|name|faculty[id|name]]"]
SEMESTER_PATTERN = re.compile(r"^\s*([1-9]\d?)\s+semestr", re.IGNORECASE)


def _polish_text(value: usos.LangDict | None) -> str:
    return (value.pl if value else None) or ""


def select_programmes(student_programmes: list[usos.StudentProgramme]) -> list[usos.StudentProgramme]:
    """Return each active programme once, primary first, in the same order on every login."""
    active = [
        student_programme
        for student_programme in student_programmes
        if student_programme.status == "active" and student_programme.programme and student_programme.programme.id
    ]
    active.sort(key=lambda item: (not item.is_primary, item.programme.id))

    unique: dict[str, usos.StudentProgramme] = {}
    for student_programme in active:
        unique.setdefault(student_programme.programme.id, student_programme)
    return list(unique.values())


def parse_semester(stages: list[usos.ProgrammeStage] | None) -> int | None:
    """Read the semester from stage descriptions such as "7 semestr, informatyka techniczna".

    USOS has no numeric semester field. Stages naming different semesters leave it unknown.
    """
    matches = (SEMESTER_PATTERN.match(_polish_text(stage.description)) for stage in stages or [])
    semesters = {int(match.group(1)) for match in matches if match}
    return semesters.pop() if len(semesters) == 1 else None


async def _store_programme(programme: usos.Programme) -> StudyProgramme:
    faculty = None
    if programme.faculty and programme.faculty.id:
        faculty, _ = await Faculty.objects.aupdate_or_create(
            id=programme.faculty.id,
            defaults={"name": _polish_text(programme.faculty.name)},
        )
    study_programme, _ = await StudyProgramme.objects.aupdate_or_create(
        id=programme.id,
        defaults={"name": _polish_text(programme.name), "faculty": faculty},
    )
    return study_programme


@sync_to_async
@transaction.atomic
def _replace_student_programmes(user: User, student_programmes: list[StudentProgramme]) -> None:
    StudentProgramme.objects.filter(user=user).delete()
    StudentProgramme.objects.bulk_create(student_programmes)


async def sync_user_studies(client, user: User) -> None:
    """Refresh the user's programmes and semesters, keeping the stored ones if USOS fails.

    These are optional extras, so a failure here must never block the login.
    """
    try:
        response = await client.programme_service.get_student_programmes(fields=STUDENT_PROGRAMME_FIELDS)
        student_programmes = [
            StudentProgramme(
                user=user,
                programme=await _store_programme(selected.programme),
                semester=parse_semester(selected.stages),
                is_primary=index == 0,
            )
            for index, selected in enumerate(select_programmes(response))
        ]
        await _replace_student_programmes(user, student_programmes)
    except Exception as e:
        logger.warning("Failed to sync USOS studies for user %s: %s", user.id, type(e).__name__)
