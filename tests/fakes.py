"""실제 API 없이 흐름을 검사하기 위한 가짜 모델과 가짜 임베더."""
from __future__ import annotations

import hashlib
from pathlib import Path

from src.config import Settings
from src.learner import LearnerRepository, connect
from src.llm import Analyzer, Generator
from src.pipeline import TutorPipeline
from src.rag import Retriever, load_entries
from src.schemas import (AnalysisOutput, Candidate, FeedbackItem, PracticeQuestion, ProfileUpdateCall,
                         TutorOutput)

ROOT = Path(__file__).resolve().parents[1]


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = dict(api_key="offline", model="fake-model", embedding_model="fake-embedding",
                  database_path=tmp_path / "test.sqlite3", feedback_min_confidence=0.6,
                  record_min_confidence=0.75, evidence_min_score=0.25, category_bonus=0.03,
                  top_k=2, hourly_limit=20, retries=1)
    values.update(overrides)
    return Settings(**values)


class FakeEmbedder:
    """글자 두 개씩 묶어 센 벡터. 글자가 많이 겹칠수록 유사도가 높다."""
    model = "fake-embedding"
    DIM = 256

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        vectors = []
        for text in texts:
            vector = [0.0] * self.DIM
            for a, b in zip(text, text[1:]):
                vector[int(hashlib.md5((a + b).encode()).hexdigest(), 16) % self.DIM] += 1.0
            vectors.append(vector)
        return vectors


def analysis_for(utterance: str) -> AnalysisOutput:
    candidates = []
    if "책이" in utterance:
        candidates.append(Candidate(expression="책이", occurrence=1, category="particle", judgment="error",
                                    suggestion="책을", explanation="'읽다'의 대상에는 '을'을 써요.", confidence=0.95))
    if "근데" in utterance:
        candidates.append(Candidate(expression="근데", occurrence=1, category="honorific", judgment="acceptable",
                                    suggestion="근데", explanation="대화에서는 자연스러워요.", confidence=0.9))
    return AnalysisOutput(candidates=candidates, summary="잘 썼어요.")


def tutor_for(context: dict) -> TutorOutput:
    items, calls = [], []
    for finding in context["findings"]:
        sources = [e["id"] for e in context["evidence"].get(str(finding["index"]), [])]
        items.append(FeedbackItem(index=finding["index"], explanation="대상에는 '을/를'을 붙여요.",
                                  evidence_ids=sources[:1]))
        if sources:
            calls.append(ProfileUpdateCall(index=finding["index"], grammar_id=sources[0], reason="조사 선택 실수"))
    first = next(iter(context["evidence"].values()), [])
    question = PracticeQuestion(prompt="어제 영화 ___ 봤어요.", choices=["이", "를", "에"], answer_index=1,
                                explanation="'보다'의 대상이라서 '를'이에요.",
                                grammar_id=first[0]["id"] if first else "")
    return TutorOutput(overall="조사만 고치면 돼요.", items=items, tool_calls=calls, question=question)


class FakeModel:
    """GeminiClient 자리에 들어가는 가짜. parse()가 미리 정한 답을 돌려준다."""

    def __init__(self, analysis=analysis_for, tutor=tutor_for):
        self.analysis = analysis
        self.tutor = tutor
        self.calls: list[str] = []

    def parse(self, system, payload, schema):
        self.calls.append(schema.__name__)
        if schema is AnalysisOutput:
            return self.analysis(payload["utterance"]), 1
        return self.tutor(payload), 1


def make_pipeline(tmp_path: Path, model: FakeModel | None = None, **overrides):
    settings = make_settings(tmp_path, **overrides)
    model = model or FakeModel()
    repository = LearnerRepository(connect(settings.database_path))
    repository.ensure_learner("tester")
    retriever = Retriever(load_entries(ROOT / "data" / "grammar.json"), FakeEmbedder(), settings)
    pipeline = TutorPipeline(repository, Analyzer(model, settings), retriever, Generator(model), settings)
    return pipeline, repository, model
