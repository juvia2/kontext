from __future__ import annotations

from pathlib import Path

import pytest

from src.learner import connect
from src.learner import LearnerRepository
from src.rag import Retriever, load_chunks
from src.llm import ErrorCategory, Judgment, LanguageAnalysis, LanguageError
from src.llm import FeedbackItem, FeedbackOutput, ProfileUpdateProposal
from src.llm import PracticeQuestion, PracticeSet, TutorResponse
from src.pipeline import PipelineFailure, TutorPipeline
from src.llm import Analyzer


ROOT = Path(__file__).resolve().parents[1]


class FakeEmbedder:
    model = "fake-test-embedder"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "어서" in text or "연결" in text else [0.0, 1.0] for text in texts]


class FakeAnalyzer:
    def analyze(self, utterance: str) -> LanguageAnalysis:
        if "먹었어서" not in utterance:
            return LanguageAnalysis(utterance=utterance, errors=[], overall_feedback="자연스럽습니다.")
        return LanguageAnalysis(
            utterance=utterance,
            errors=[LanguageError(expression="먹었어서", category=ErrorCategory.CONNECTIVE_ENDING,
                                  judgment=Judgment.LESS_NATURAL, explanation="문맥상 다른 연결도 가능해요.",
                                  suggestion="먹어서", confidence=0.86)],
            overall_feedback="연결 표현을 살펴보세요.",
        )


class FakeGenerator:
    def respond(self, context: dict) -> TutorResponse:
        feedback = FeedbackOutput(
            overall="문맥에 맞는 연결을 연습해 보세요.",
            items=[FeedbackItem(error_index=0, correction="이미 먹어서", explanation="원인을 간결하게 연결할 수 있어요.",
                                natural_alternative="밥을 이미 먹었기 때문에 카페에 갔어요.",
                                personalized_insight="이전에도 연결어미를 연습했어요.",
                                evidence_ids=[context["evidence"]["0"][0]["id"]])],
            profile_updates=[ProfileUpdateProposal(error_index=0, error_type="connective_ending",
                                                   expression="먹었어서", suggestion="먹어서")],
        )
        question = PracticeQuestion(
            question="더 자연스러운 연결은?", choices=["먹었어서", "먹어서", "먹는데"],
            answer_index=1, explanation="이 문맥에서는 원인을 연결합니다.", target_category="connective_ending",
        )
        return TutorResponse(feedback=feedback, question=question)

def make_pipeline(tmp_path: Path) -> tuple[TutorPipeline, LearnerRepository]:
    repository = LearnerRepository(connect(tmp_path / "tutor.sqlite3"))
    repository.ensure_learner("test_user")
    repository.seed_demo_history("test_user")
    retriever = Retriever(load_chunks(ROOT / "data" / "grammar.json"), FakeEmbedder())
    return TutorPipeline(repository, FakeAnalyzer(), retriever, FakeGenerator()), repository


def test_full_workflow_updates_profile_and_exposes_evidence(tmp_path: Path) -> None:
    pipeline, repository = make_pipeline(tmp_path)
    before = repository.get_profile("test_user").recent_patterns["connective_ending"]
    result = pipeline.run("test_user", "이미 먹었어서 카페에 갔어요.")
    assert result.analysis.errors[0].judgment == Judgment.LESS_NATURAL
    assert result.evidence[0][0].chunk.document_id == "ending-eoseo"
    assert result.tool_results[0].status == "updated"
    assert repository.get_profile("test_user").recent_patterns["connective_ending"] == before + 1
    assert len(result.practice.questions) == 1
    assert "Augmented Context" in [step["name"] for step in result.trace.steps]


def test_no_false_positive_skips_generation_and_update(tmp_path: Path) -> None:
    pipeline, repository = make_pipeline(tmp_path)
    result = pipeline.run("test_user", "어제 친구와 영화를 봤어요.")
    assert result.analysis.errors == []
    assert result.practice.questions == []
    assert result.tool_results == []
    assert len(repository.recent_history("test_user")) == 5


def test_invalid_tool_proposal_cannot_write(tmp_path: Path) -> None:
    pipeline, repository = make_pipeline(tmp_path)
    analysis = FakeAnalyzer().analyze("이미 먹었어서 갔어요.")
    evidence = pipeline.retriever.retrieve("연결 어서", "connective_ending")
    bad = ProfileUpdateProposal(error_index=0, error_type="tense", expression="먹었어서", suggestion="먹어서")
    before = repository.get_profile("test_user").recent_patterns["connective_ending"]
    result = pipeline.tools.update(learner_id="test_user", request_id="fixed-id", proposal=bad,
                                   analysis=analysis, evidence=evidence)
    assert result.status == "rejected"
    assert repository.get_profile("test_user").recent_patterns["connective_ending"] == before


def test_empty_input_returns_trace(tmp_path: Path) -> None:
    pipeline, _ = make_pipeline(tmp_path)
    with pytest.raises(PipelineFailure) as failure:
        pipeline.run("test_user", "  ")
    assert failure.value.trace.steps[0]["status"] == "failed"


def test_batch_update_is_atomic_on_database_error(tmp_path: Path) -> None:
    import sqlite3

    _, repository = make_pipeline(tmp_path)
    repository.connection.execute(
        "CREATE TRIGGER reject_test BEFORE INSERT ON error_history "
        "WHEN NEW.expression = 'fail' BEGIN SELECT RAISE(ABORT, 'test failure'); END"
    )
    before = len(repository.recent_history("test_user", 100))
    rows = [
        ("test_user", "atomic", 0, "first", "tense", "fixed", 0.9),
        ("test_user", "atomic", 1, "fail", "tense", "fixed", 0.9),
    ]
    with pytest.raises(sqlite3.DatabaseError):
        repository.record_errors_batch(rows)
    assert len(repository.recent_history("test_user", 100)) == before


def test_tool_update_is_idempotent(tmp_path: Path) -> None:
    pipeline, repository = make_pipeline(tmp_path)
    analysis = FakeAnalyzer().analyze("이미 먹었어서 갔어요.")
    evidence = pipeline.retriever.retrieve("연결 어서", "connective_ending")
    proposal = ProfileUpdateProposal(error_index=0, error_type="connective_ending",
                                     expression="먹었어서", suggestion="먹어서")
    before = repository.get_profile("test_user").recent_patterns["connective_ending"]
    first = pipeline.tools.update_many(learner_id="test_user", request_id="same-request",
                                       proposals=[proposal], analysis=analysis, evidence={0: evidence})
    second = pipeline.tools.update_many(learner_id="test_user", request_id="same-request",
                                        proposals=[proposal], analysis=analysis, evidence={0: evidence})
    assert first[0].status == "updated"
    assert second[0].status == "already_recorded"
    assert repository.get_profile("test_user").recent_patterns["connective_ending"] == before + 1


def test_uncited_retrieval_does_not_update_profile(tmp_path: Path) -> None:
    pipeline, repository = make_pipeline(tmp_path)

    class UncitedGenerator(FakeGenerator):
        def respond(self, context: dict) -> TutorResponse:
            output = super().respond(context)
            output.feedback.items[0].evidence_ids = []
            return output

    pipeline.generator = UncitedGenerator()
    before = repository.get_profile("test_user").recent_patterns["connective_ending"]
    result = pipeline.run("test_user", "이미 먹었어서 카페에 갔어요.")
    assert result.tool_results[0].status == "rejected"
    assert repository.get_profile("test_user").recent_patterns["connective_ending"] == before


def test_analyzer_ignores_unchanged_correction() -> None:
    class NoOpModel:
        def parse(self, system, payload, schema):
            return LanguageAnalysis(
                utterance=payload["utterance"],
                errors=[LanguageError(expression="읽었어요", category=ErrorCategory.GRAMMAR,
                                      judgment=Judgment.ERROR, explanation="검토 필요",
                                      suggestion="읽었어요", confidence=0.9)],
                overall_feedback="다시 살펴봐요.",
            )

    result = Analyzer(NoOpModel()).analyze("어제 책을 읽었어요.")
    assert result.errors == []
