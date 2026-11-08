from pydantic import BaseModel


class Answer(BaseModel):
    id: str
    order: int
    text: str
    is_correct: bool


class Question(BaseModel):
    id: str
    order: int
    text: str
    explanation: str
    multiple: bool
    answers: list[Answer]


class Quiz(BaseModel):
    title: str
    description: str
    version: int
    questions: list[Question]
