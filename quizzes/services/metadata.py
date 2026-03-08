def get_preview_question(quiz):
    """
    Finds a suitable preview question for the quiz.
    Criteria:
    - No image in question
    - No image in answers
    - At least 3 answers
    - Returns the first matching question based on order
    """
    questions = quiz.questions.prefetch_related("answers").order_by("order")

    for question in questions:
        if question.image_url or question.image_upload_id:
            continue

        answers = question.answers.all()
        if len(answers) < 3:
            continue

        has_answer_images = any(a.image_url or a.image_upload_id for a in answers)
        if has_answer_images:
            continue

        return question

    return None
