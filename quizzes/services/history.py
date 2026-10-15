"""
Version history of quiz content.

Every change to a quiz's title, description, questions, or answers records a
`QuizVersion` with a snapshot of the content afterwards. Changes go through
`track_quiz_change`, which also records the content from before the first
tracked change of an older quiz, so it can be restored too.

Consecutive changes by the same author from the same place within
`MERGE_WINDOW` update one version instead of adding many, so saving often
does not bury earlier versions. At most `MAX_VERSIONS` are kept per quiz.
"""

import json
import zlib
from contextlib import contextmanager
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from quizzes.models import Question, Quiz, QuizVersion, QuizVersionSource
from uploads.models import UploadedImage

MERGE_WINDOW = timedelta(minutes=10)
MAX_VERSIONS = 100

# Sources whose consecutive changes may be merged into one version.
MERGEABLE_SOURCES = {QuizVersionSource.EDITOR, QuizVersionSource.QUESTION, QuizVersionSource.MCP}

QUESTION_FIELDS = (
    "order",
    "text",
    "explanation",
    "multiple",
    "question_type",
    "is_markdown_enabled",
    "is_ai_generated",
    "is_flashcard",
    "image_url",
)
ANSWER_FIELDS = ("order", "text", "is_correct", "image_url")


def _id(value):
    return None if value is None else str(value)


def build_snapshot(quiz):
    """The quiz content as plain data, in a stable order."""
    questions = Question.objects.filter(quiz=quiz).prefetch_related("answers").order_by("order", "id")
    return {
        "title": quiz.title,
        "description": quiz.description or "",
        "questions": [
            {
                "id": str(question.id),
                **{field: getattr(question, field) for field in QUESTION_FIELDS},
                "image_upload": _id(question.image_upload_id),
                "answers": [
                    {
                        "id": str(answer.id),
                        **{field: getattr(answer, field) for field in ANSWER_FIELDS},
                        "image_upload": _id(answer.image_upload_id),
                    }
                    for answer in sorted(question.answers.all(), key=lambda a: (a.order, str(a.id)))
                ],
            }
            for question in questions
        ],
    }


def encode_snapshot(snapshot):
    return zlib.compress(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode())


def decode_snapshot(data):
    return json.loads(zlib.decompress(bytes(data)))


def summarize(before, after):
    """How `after` differs from `before`, counted per question."""
    if before is None:
        return {"created": True, "added": len(after["questions"])}
    old = {question["id"]: question for question in before["questions"]}
    new = {question["id"]: question for question in after["questions"]}
    summary = {
        "added": len(new.keys() - old.keys()),
        "removed": len(old.keys() - new.keys()),
        "changed": sum(
            1
            for question_id in new.keys() & old.keys()
            if {**new[question_id], "order": None} != {**old[question_id], "order": None}
        ),
        "reordered": [q["id"] for q in before["questions"] if q["id"] in new]
        != [q["id"] for q in after["questions"] if q["id"] in old],
        "title": before["title"] != after["title"],
        "description": before["description"] != after["description"],
    }
    return {key: value for key, value in summary.items() if value}


def _save_version(quiz, snapshot, *, author, source, previous, restored_from=None, created_at=None):
    now = timezone.now()
    return QuizVersion.objects.create(
        quiz=quiz,
        version=quiz.version,
        author=author,
        source=source,
        restored_from=restored_from,
        created_at=created_at or now,
        updated_at=created_at or now,
        title=snapshot["title"],
        question_count=len(snapshot["questions"]),
        # The content from before history has no known change to describe.
        summary={} if source == QuizVersionSource.BASELINE else summarize(previous, snapshot),
        snapshot=encode_snapshot(snapshot),
    )


def _prune(quiz):
    stale = quiz.versions.order_by("-version").values_list("id", flat=True)[MAX_VERSIONS:]
    QuizVersion.objects.filter(id__in=list(stale)).delete()


def record_created(quiz, *, user, source):
    """Records the first version of a quiz which was just created."""
    _save_version(quiz, build_snapshot(quiz), author=user, source=source, previous=None)


def _record(quiz, before, after, *, user, source, restored_from):
    latest = quiz.versions.order_by("-version").first()
    author = user if getattr(user, "is_authenticated", False) else None
    now = timezone.now()
    if (
        latest is not None
        and author is not None
        and latest.author_id == author.id
        and latest.source == source
        and source in MERGEABLE_SOURCES
        and restored_from is None
        and now - latest.updated_at <= MERGE_WINDOW
    ):
        # Continue the author's latest version rather than adding another.
        earlier = quiz.versions.filter(version__lt=latest.version).order_by("-version").first()
        latest.version = quiz.version
        latest.updated_at = now
        latest.title = after["title"]
        latest.question_count = len(after["questions"])
        latest.summary = summarize(decode_snapshot(earlier.snapshot) if earlier else None, after)
        latest.snapshot = encode_snapshot(after)
        latest.save()
        return latest
    version = _save_version(quiz, after, author=author, source=source, previous=before, restored_from=restored_from)
    _prune(quiz)
    return version


def ensure_baseline(quiz, snapshot=None):
    """Gives a quiz from before history existed a first version with its
    current content, so that content stays restorable. Call inside a
    transaction which locked the quiz."""
    if quiz.versions.exists():
        return
    _save_version(
        quiz,
        snapshot if snapshot is not None else build_snapshot(quiz),
        author=None,
        source=QuizVersionSource.BASELINE,
        previous=None,
        created_at=quiz.updated_at,
    )


@contextmanager
def track_quiz_change(quiz, *, user, source, restored_from=None):
    """Records a version when the content of `quiz` changes inside the block.

    Bumps `Quiz.version` when the block changed the content without doing so.
    Yields the quiz as locked and freshly loaded; write version numbers from it.
    """
    with transaction.atomic():
        # Serializes concurrent changes, so versions are numbered in order.
        locked = Quiz.objects.select_for_update().get(pk=quiz.pk)
        before = build_snapshot(locked)
        ensure_baseline(locked, before)
        version_before = locked.version
        yield locked
        locked.refresh_from_db()
        after = build_snapshot(locked)
        if after == before:
            if locked.version < version_before:
                # The block wrote back a stale, lower version without changing content.
                Quiz.objects.filter(pk=locked.pk).update(version=version_before)
                locked.refresh_from_db(fields=["version"])
                quiz.version = locked.version
            return
        if locked.version <= version_before:
            # The block did not move the version on, or wrote back a stale,
            # lower one from an instance loaded before another save.
            Quiz.objects.filter(pk=locked.pk).update(version=version_before + 1)
            locked.refresh_from_db(fields=["version"])
        quiz.version = locked.version
        _record(locked, before, after, user=user, source=source, restored_from=restored_from)


def restore_payload(snapshot):
    """Quiz serializer data for a snapshot. Uploaded images which no longer
    exist are dropped, keeping any image URL."""
    upload_ids = {question["image_upload"] for question in snapshot["questions"] if question["image_upload"]} | {
        answer["image_upload"]
        for question in snapshot["questions"]
        for answer in question["answers"]
        if answer["image_upload"]
    }
    existing = {str(pk) for pk in UploadedImage.objects.filter(id__in=upload_ids).values_list("id", flat=True)}

    def upload(value):
        return value if value in existing else None

    return {
        "title": snapshot["title"],
        "description": snapshot["description"],
        "questions": [
            {
                **{key: value for key, value in question.items() if key not in {"answers", "image_upload"}},
                "image_upload": upload(question["image_upload"]),
                "answers": [
                    {
                        **{key: value for key, value in answer.items() if key != "image_upload"},
                        "image_upload": upload(answer["image_upload"]),
                    }
                    for answer in question["answers"]
                ],
            }
            for question in snapshot["questions"]
        ],
    }
