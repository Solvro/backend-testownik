import json
import logging
import uuid
import zlib

from django.db import migrations, transaction

logger = logging.getLogger(__name__)
QUESTION_BATCH_SIZE = 20_000
VERSION_BATCH_SIZE = 200


def batches(queryset, size):
    """Keyset pagination also works for the UUID primary keys used here."""
    last = None
    while True:
        page = queryset.order_by("pk")
        if last is not None:
            page = page.filter(pk__gt=last)
        ids = list(page.values_list("pk", flat=True)[:size])
        if not ids:
            return
        yield queryset.filter(pk__gte=ids[0], pk__lte=ids[-1])
        last = ids[-1]


def correct_first(answers, fallback, question_id):
    marked = [i for i, answer in enumerate(answers) if answer["is_correct"]]
    if len(marked) == 1:
        return marked[0] == 0
    if fallback is not None:
        return fallback
    logger.warning("True/false question %s has ambiguous correctness; marking the first answer correct", question_id)
    return True


def normalize_answers(answers, first_correct, *, preserve_correct=False):
    keep_labels = len(answers) == 2 and all(answer.get("text", "").strip() for answer in answers)
    marked = [i for i, answer in enumerate(answers) if answer["is_correct"]]
    if preserve_correct and len(marked) == 1 and marked[0] >= 2:
        # Keep the sole correct answer even if it used to be an extra option.
        answers = [answers[0], answers[marked[0]]]
    normalized = []
    for i, label in enumerate(("Prawda", "Fałsz")):
        answer = (
            dict(answers[i])
            if i < len(answers)
            else {
                "id": str(uuid.uuid4()),
                "image_url": None,
                "image_upload": None,
            }
        )
        answer.update(order=i + 1, text=answer["text"] if keep_labels else label, is_correct=first_correct == (i == 0))
        normalized.append(answer)
    return normalized


def convert_snapshots(apps, db, *, reverse):
    Version = apps.get_model("quizzes", "QuizVersion")
    Question = apps.get_model("quizzes", "Question")
    versions = Version.objects.using(db)
    for page in batches(versions, VERSION_BATCH_SIZE):
        decoded = [(version, json.loads(zlib.decompress(bytes(version.snapshot)))) for version in page]
        live_tf = {}
        if not reverse:
            ids = [q["id"] for _, snapshot in decoded for q in snapshot["questions"] if q["question_type"] == 2]
            live_tf = {
                str(pk): value
                for pk, value in Question.objects.using(db).filter(pk__in=ids).values_list("pk", "tf_answer")
            }
        for version, snapshot in decoded:
            for question in snapshot["questions"]:
                if reverse:
                    kind = question.pop("type")
                    question["question_type"] = {"open": 1, "true_false": 2}.get(kind, 0)
                    question["multiple"] = kind == "multiple_choice"
                    question["is_flashcard"] = False
                    if kind == "true_false":
                        answers = sorted(question["answers"], key=lambda a: (a["order"], a["id"]))
                        question["tf_answer"] = correct_first(answers, None, question["id"])
                    question.pop("shuffle_answers", None)
                    question.pop("open_matching", None)
                else:
                    kind = question.pop("question_type")
                    multiple = question.pop("multiple")
                    question.pop("is_flashcard", None)
                    question.pop("tf_answer", None)
                    question["type"] = {1: "open", 2: "true_false"}.get(
                        kind, "multiple_choice" if multiple else "single_choice"
                    )
                    question["shuffle_answers"] = kind != 2
                    question["open_matching"] = "exact"
                    if kind == 2:
                        answers = sorted(question["answers"], key=lambda a: (a["order"], a["id"]))
                        first = correct_first(answers, live_tf.get(question["id"]), question["id"])
                        question["answers"] = normalize_answers(answers, first, preserve_correct=True)
            version.snapshot = zlib.compress(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode())
        versions.bulk_update([version for version, _ in decoded], ["snapshot"], batch_size=VERSION_BATCH_SIZE)


def forwards(apps, schema_editor):
    Question = apps.get_model("quizzes", "Question")
    Answer = apps.get_model("quizzes", "Answer")
    db = schema_editor.connection.alias
    questions = Question.objects.using(db)
    for page in batches(questions, QUESTION_BATCH_SIZE):
        page.filter(question_type=0, multiple=True).update(type="multiple_choice")
        page.filter(question_type=0, multiple=False).update(type="single_choice")
        page.filter(question_type=1).update(type="open")
        page.filter(question_type=2).update(type="true_false", shuffle_answers=False)
    for question in questions.filter(question_type=2).iterator(chunk_size=1000):
        with transaction.atomic(using=db):
            answers = list(
                Answer.objects.using(db)
                .filter(question_id=question.pk)
                .order_by("order", "pk")
                .values("id", "order", "text", "is_correct", "image_url", "image_upload_id")
            )
            first = question.tf_answer
            if first is None:
                first = correct_first(answers, None, question.pk)
            normalized = normalize_answers(answers, first, preserve_correct=question.tf_answer is None)
            Answer.objects.using(db).filter(question_id=question.pk).exclude(
                pk__in=[a["id"] for a in normalized]
            ).delete()
            for answer in normalized:
                answer_id = answer.pop("id")
                # New snapshot answers use image_upload; live values use its ID.
                answer.pop("image_upload", None)
                Answer.objects.using(db).update_or_create(pk=answer_id, defaults={"question_id": question.pk, **answer})
    convert_snapshots(apps, db, reverse=False)


def backwards(apps, schema_editor):
    Question = apps.get_model("quizzes", "Question")
    Answer = apps.get_model("quizzes", "Answer")
    db = schema_editor.connection.alias
    questions = Question.objects.using(db)
    for page in batches(questions, QUESTION_BATCH_SIZE):
        page.update(question_type=0, multiple=False, tf_answer=None)
        page.filter(type="multiple_choice").update(multiple=True)
        page.filter(type="open").update(question_type=1)
        page.filter(type="true_false").update(question_type=2)
    for question in questions.filter(type="true_false").iterator(chunk_size=1000):
        answers = list(
            Answer.objects.using(db).filter(question_id=question.pk).order_by("order", "pk").values("is_correct")
        )
        questions.filter(pk=question.pk).update(tf_answer=correct_first(answers, None, question.pk))
    convert_snapshots(apps, db, reverse=True)


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("quizzes", "0035_question_type_fields")]
    operations = [migrations.RunPython(forwards, backwards)]
