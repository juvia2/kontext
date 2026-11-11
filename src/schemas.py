"""모델과 주고받는 데이터의 모양.

위쪽은 Gemini가 반환해야 하는 JSON(모델 출력), 아래쪽은 앱이 그 출력을 검사한 뒤 쓰는 데이터다.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Category(str, Enum):
    PARTICLE = "particle"
    ENDING = "ending"
    TENSE = "tense"
    HONORIFIC = "honorific"
    PATTERN = "pattern"
    WORD = "word"
    SPELLING = "spelling"


CATEGORY_LABELS = {
    Category.PARTICLE: "조사",
    Category.ENDING: "어미",
    Category.TENSE: "시제",
    Category.HONORIFIC: "높임·말투",
    Category.PATTERN: "문형",
    Category.WORD: "어휘",
    Category.SPELLING: "맞춤법",
}


class Judgment(str, Enum):
    ERROR = "error"                # 문법·표기가 틀림
    LESS_NATURAL = "less_natural"  # 틀리지는 않지만 더 나은 표현이 있음
    ACCEPTABLE = "acceptable"      # 학습자가 헷갈릴 만하지만 괜찮음
    UNCERTAIN = "uncertain"        # 문맥이 부족해 판단을 미룸


JUDGMENT_LABELS = {
    Judgment.ERROR: "오류",
    Judgment.LESS_NATURAL: "덜 자연스러움",
    Judgment.ACCEPTABLE: "괜찮음",
    Judgment.UNCERTAIN: "판단 보류",
}


# ── 모델 출력 1: 문장 분석 ────────────────────────────────────────────────

class Candidate(BaseModel):
    expression: str = Field(min_length=1, description="원문에 있는 그대로의 표현(띄어쓰기 포함)")
    occurrence: int = Field(ge=1, description="같은 표현이 여러 번 나오면 몇 번째인지. 보통 1")
    category: Category
    judgment: Judgment
    suggestion: str = Field(min_length=1, description="expression 자리에 그대로 바꿔 넣을 표현")
    explanation: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class AnalysisOutput(BaseModel):
    candidates: list[Candidate] = Field(max_length=6)
    summary: str = Field(min_length=1)


# ── 모델 출력 2: 피드백, 연습문제, 도구 호출 제안 ──────────────────────────

class FeedbackItem(BaseModel):
    index: int = Field(ge=0, description="findings의 index")
    explanation: str = Field(min_length=1)
    evidence_ids: list[str] = Field(description="설명에 실제로 사용한 문법 자료 id")


class ProfileUpdateCall(BaseModel):
    """update_learner_profile 도구의 인자. 모델은 호출을 제안만 하고 실행은 앱이 한다."""
    index: int = Field(ge=0, description="기록할 finding의 index")
    grammar_id: str = Field(min_length=1, description="이 실수가 속하는 문법 자료 id")
    reason: str = Field(min_length=1, description="기록할 가치가 있다고 본 이유 한 문장")


class PracticeQuestion(BaseModel):
    prompt: str = Field(min_length=1)
    choices: list[str] = Field(min_length=3, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1)
    grammar_id: str = Field(description="문제가 다루는 문법 자료 id")

    @model_validator(mode="after")
    def check_choices(self) -> "PracticeQuestion":
        if self.answer_index >= len(self.choices):
            raise ValueError("answer_index가 선택지 범위를 벗어났습니다")
        if len({choice.strip() for choice in self.choices}) != len(self.choices):
            raise ValueError("선택지가 중복되었습니다")
        return self


class TutorOutput(BaseModel):
    overall: str = Field(min_length=1)
    items: list[FeedbackItem]
    tool_calls: list[ProfileUpdateCall]
    question: PracticeQuestion


# ── 앱이 검사한 뒤 쓰는 데이터 ────────────────────────────────────────────

class Finding(BaseModel):
    index: int
    start: int
    end: int
    expression: str
    suggestion: str
    category: Category
    judgment: Judgment
    explanation: str
    confidence: float
    actionable: bool


class Analysis(BaseModel):
    utterance: str
    findings: list[Finding]
    summary: str
    dropped: list[dict]
    attempts: int = 1
