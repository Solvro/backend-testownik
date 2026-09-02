import os
from uuid import uuid4

from django.conf import settings
from openai import OpenAI

from .prompts import PROMPT_QUIZ_GENERATOR
from .quiz_schema import Quiz


def get_openai_client() -> OpenAI:
    api_key = getattr(settings, "OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
    return OpenAI(api_key=api_key)


def generate_quiz(
        chunk: str,
        question_count: int = 3,
        difficulty: str = "medium"
        ) -> tuple[Quiz, dict]:
    client = get_openai_client()
    base_prompt = PROMPT_QUIZ_GENERATOR

    prompt = f"""
Generate quiz strictly from this content:
question_count: {question_count}
difficulty: {difficulty}

content:
{chunk}
"""

    model_name = getattr(settings, "OPENAI_QUIZ_MODEL", "gpt-4o-mini")

    response = client.beta.chat.completions.parse(
        model=model_name,
        messages=[
            {"role": "system", "content": base_prompt},
            {"role": "user", "content": prompt}
            ],
        response_format=Quiz
    )

    usage_info = {
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
        "cached_tokens": getattr(response.usage.prompt_tokens_details, "cached_tokens", 0) if hasattr(response.usage, "prompt_tokens_details") else 0,
        "model": model_name,
    }

    return response.choices[0].message.parsed, usage_info


def fix_quiz(quiz: dict) -> dict:
    return {
        **quiz,
        "questions": [
            {
                **q,
                "id": str(uuid4()),
                "order": i+1,
                "answers": [
                    {
                        **a,
                        "id": str(uuid4()),
                        "order": j+1,
                    }
                    for j, a in enumerate(q.get("answers", []))
                ],
            }
            for i, q in enumerate(quiz.get("questions", []))
        ],
    }
