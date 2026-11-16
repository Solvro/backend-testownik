"""Authorize shared image references without repeating one lookup per field."""

import uuid

from django.db.models import Q
from rest_framework import serializers

from uploads.models import UploadedImage


def _requested_image_ids(data, *, nested_questions):
    if not isinstance(data, dict):
        return set()
    questions = data.get("questions", []) if nested_questions else [data]
    if not isinstance(questions, list):
        return set()
    ids = set()
    for question in questions:
        if not isinstance(question, dict):
            continue
        answers = question.get("answers", [])
        items = [question, *(answers if isinstance(answers, list) else [])]
        for item in items:
            if not isinstance(item, dict) or item.get("image_upload") is None:
                continue
            try:
                ids.add(uuid.UUID(str(item["image_upload"])))
            except (ValueError, TypeError, AttributeError):
                # The field reports invalid values at their normal nested path.
                continue
    return ids


def _target_quiz(root, user):
    from quizzes.models import Question, Quiz

    if isinstance(root.instance, Quiz):
        quiz = root.instance
    elif isinstance(root.instance, Question):
        quiz = root.instance.quiz
    else:
        # Only question-create serializers declare a target quiz. An unknown
        # key on quiz creation must not borrow another quiz's image allowance.
        if "quiz" not in getattr(root, "fields", {}):
            return None
        data = getattr(root, "initial_data", None)
        quiz_id = data.get("quiz") if isinstance(data, dict) else None
        if not isinstance(quiz_id, str):
            return None
        try:
            quiz_id = uuid.UUID(str(quiz_id))
        except (ValueError, TypeError, AttributeError):
            return None
        quiz = Quiz.objects.filter(pk=quiz_id).select_related("folder").first()
    # A payload cannot use another private quiz as an image-existence oracle.
    return quiz if quiz is not None and quiz.can_edit(user) else None


def _attachable_images(root, user):
    from quizzes.models import Answer, Question

    if not getattr(user, "is_authenticated", False):
        return {}
    ids = sorted(
        _requested_image_ids(
            getattr(root, "initial_data", None), nested_questions="questions" in getattr(root, "fields", {})
        )
    )
    if not ids:
        return {}
    allowed = Q(uploaded_by=user)
    quiz = _target_quiz(root, user)
    if quiz is not None:
        # Authorized copies and guest upgrades retain the original upload IDs.
        # Keep those references editable even after their uploader is deleted.
        allowed |= Q(pk__in=Question.objects.filter(quiz=quiz).values("image_upload_id"))
        allowed |= Q(pk__in=Answer.objects.filter(question__quiz=quiz).values("image_upload_id"))
    images = {}
    for start in range(0, len(ids), 500):
        images.update(UploadedImage.objects.filter(allowed, pk__in=ids[start : start + 500]).in_bulk())
    return images


class AttachableImageField(serializers.PrimaryKeyRelatedField):
    """Accept own uploads or images already attached to the editable target quiz."""

    def to_internal_value(self, data):
        image_id = serializers.UUIDField().run_validation(data)
        root = self.root
        if not hasattr(root, "_attachable_image_cache"):
            user = getattr(self.context.get("request"), "user", None)
            root._attachable_image_cache = _attachable_images(root, user)
        image = root._attachable_image_cache.get(image_id)
        if image is None:
            self.fail("does_not_exist", pk_value=data)
        return image
