from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field, model_validator

class Judgment(str, Enum):
    ERROR = "error"
    LESS_NATURAL = "less_natural"
    ACCEPTABLE = "acceptable"
    UNCERTAIN = "uncertain"


class ErrorCategory(str, Enum):
    GRAMMAR = "grammar"
    PARTICLE_SELECTION = "particle_selection"
    CONNECTIVE_ENDING = "connective_ending"
    TENSE = "tense"
    LEXICAL_CHOICE = "lexical_choice"
    COLLOCATION = "collocation"
    PRAGMATICS = "pragmatics"
    REGISTER = "register"
    NATURALNESS = "naturalness"


class LanguageError(BaseModel):
    expression: str = Field(min_length=1)
    category: ErrorCategory
    judgment: Judgment
    explanation: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class LanguageAnalysis(BaseModel):
    utterance: str = Field(min_length=1)
    errors: list[LanguageError]
    overall_feedback: str = Field(min_length=1)


class FeedbackItem(BaseModel):
    error_index: int = Field(ge=0)
    correction: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    natural_alternative: str = Field(min_length=1)
    personalized_insight: str = Field(min_length=1)
    evidence_ids: list[str]


class ProfileUpdateProposal(BaseModel):
    error_index: int = Field(ge=0)
    error_type: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)


class FeedbackOutput(BaseModel):
    overall: str = Field(min_length=1)
    items: list[FeedbackItem]
    profile_updates: list[ProfileUpdateProposal]


class PracticeQuestion(BaseModel):
    question: str = Field(min_length=1)
    choices: list[str] = Field(min_length=3, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1)
    target_category: str = Field(min_length=1)

    @model_validator(mode="after")
    def answer_is_present(self) -> "PracticeQuestion":
        if self.answer_index >= len(self.choices):
            raise ValueError("answer_index must refer to a choice")
        return self


class PracticeSet(BaseModel):
    questions: list[PracticeQuestion] = Field(max_length=3)


class TutorResponse(BaseModel):
    feedback: FeedbackOutput
    question: PracticeQuestion
