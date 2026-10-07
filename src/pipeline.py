from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar
from uuid import uuid4

from src.learner import LearnerRepository, ProfileTools, ToolResult
from src.llm import Analyzer, Generator
from src.rag import Retriever, SearchMatch
from src.schemas import Judgment, LanguageAnalysis, FeedbackOutput, PracticeSet

T = TypeVar("T")
logger = logging.getLogger("language_tutor")


@dataclass
class PipelineTrace:
    request_id: str = field(default_factory=lambda: str(uuid4()))
    steps: list[dict[str, Any]] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)

    def step(self, name: str, action: Callable[[], T], details: Callable[[T], Any] | None = None) -> T:
        start = time.perf_counter()
        try:
            result = action()
            entry = {"name": name, "status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 1)}
            if details is not None:
                entry["data"] = details(result)
            self.steps.append(entry)
            return result
        except Exception as exc:
            self.steps.append({"name": name, "status": "failed", "error": type(exc).__name__,
                               "message": str(exc), "latency_ms": round((time.perf_counter() - start) * 1000, 1)})
            raise

    def as_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "latency_ms": round((time.perf_counter() - self.started) * 1000, 1),
                "steps": self.steps}

    def log(self) -> None:
        logger.info("request_id=%s latency_ms=%.1f steps=%s", self.request_id,
                    (time.perf_counter() - self.started) * 1000,
                    [(step["name"], step["status"]) for step in self.steps])


class PipelineFailure(RuntimeError):
    def __init__(self, message: str, trace: PipelineTrace):
        super().__init__(message)
        self.trace = trace


@dataclass(frozen=True)
class PipelineResult:
    analysis: LanguageAnalysis
    feedback: FeedbackOutput
    practice: PracticeSet
    evidence: dict[int, list[SearchMatch]]
    tool_results: list[ToolResult]
    trace: PipelineTrace


def actionable(analysis: LanguageAnalysis) -> list[int]:
    return [index for index, item in enumerate(analysis.errors)
            if item.judgment in (Judgment.ERROR, Judgment.LESS_NATURAL) and item.confidence >= 0.65]


# Chapter 07: follow the stages in this method from input to saved result.

class TutorPipeline:
    def __init__(self, repository: LearnerRepository, analyzer: Analyzer,
                 retriever: Retriever, generator: Generator):
        self.repository = repository
        self.analyzer = analyzer
        self.retriever = retriever
        self.generator = generator
        self.tools = ProfileTools(repository)

    def run(self, learner_id: str, utterance: str) -> PipelineResult:
        trace = PipelineTrace()
        utterance = utterance.strip()
        try:
            trace.step("User Input", lambda: self._validate_input(utterance), lambda value: {"utterance": value})
            profile = trace.step("Learner Profile", lambda: self.repository.get_profile(learner_id),
                                 lambda value: value.as_context())
            analysis = trace.step("Structured Language Analysis", lambda: self.analyzer.analyze(utterance),
                                  lambda value: value.model_dump(mode="json"))
            indices = actionable(analysis)
            queries = {index: f"{analysis.errors[index].category.value}: "
                              f"{analysis.errors[index].expression} → {analysis.errors[index].suggestion}. "
                              f"{analysis.errors[index].explanation}" for index in indices}
            trace.step("Retrieval Queries", lambda: queries, lambda value: value)
            evidence = trace.step("Retrieved Knowledge", lambda: {
                index: self.retriever.retrieve(query, analysis.errors[index].category.value)
                for index, query in queries.items()
            }, lambda value: {str(i): [self._match_dict(match) for match in matches]
                               for i, matches in value.items()})
            context = self._context(utterance, analysis, profile.as_context(), evidence, indices)
            trace.step("Augmented Context", lambda: context, lambda value: value)
            if indices:
                response = trace.step("Feedback and Practice", lambda: self.generator.respond(context),
                                      lambda value: value.model_dump(mode="json"))
                feedback = response.feedback
                practice = PracticeSet(questions=[response.question])
                self._validate_feedback(feedback, indices, evidence)
            else:
                feedback = FeedbackOutput(overall=analysis.overall_feedback, items=[], profile_updates=[])
                practice = PracticeSet(questions=[])
                trace.step("Feedback and Practice",
                           lambda: {"feedback": feedback.model_dump(mode="json"),
                                    "practice": practice.model_dump(mode="json")})
            proposals = feedback.profile_updates
            trace.step("Tool Call Proposals", lambda: proposals,
                       lambda value: [item.model_dump() for item in value])
            cited = {item.error_index: set(item.evidence_ids) for item in feedback.items}
            cited_evidence = {index: [match for match in matches if match.chunk.id in cited.get(index, set())]
                              for index, matches in evidence.items()}
            tool_results = trace.step("Tool Results", lambda: self.tools.update_many(
                learner_id=learner_id, request_id=trace.request_id, proposals=proposals,
                analysis=analysis, evidence=cited_evidence,
            ), lambda value: [item.as_dict() for item in value])
            trace.log()
            return PipelineResult(analysis, feedback, practice, evidence, tool_results, trace)
        except Exception as exc:
            trace.log()
            raise PipelineFailure(str(exc), trace) from exc

    @staticmethod
    def _validate_input(utterance: str) -> str:
        if not utterance:
            raise ValueError("한국어 발화를 입력해 주세요.")
        if len(utterance) > 2000:
            raise ValueError("입력은 2,000자 이하로 제한됩니다.")
        return utterance

    @staticmethod
    def _match_dict(match: SearchMatch) -> dict:
        return {"id": match.chunk.id, "document_id": match.chunk.document_id,
                "title": match.chunk.title, "text": match.chunk.text,
                "source": match.chunk.source, "source_urls": match.chunk.source_urls,
                "score": round(match.score, 4)}

    @classmethod
    def _context(cls, utterance: str, analysis: LanguageAnalysis, profile: dict,
                 evidence: dict[int, list[SearchMatch]], indices: list[int]) -> dict:
        return {"utterance": utterance, "analysis": analysis.model_dump(mode="json"),
                "learner_profile": profile, "actionable_error_indices": indices,
                "evidence": {str(index): [cls._match_dict(match) for match in matches]
                             for index, matches in evidence.items()}}

    @staticmethod
    def _validate_feedback(feedback: FeedbackOutput, indices: list[int],
                           evidence: dict[int, list[SearchMatch]]) -> None:
        returned = [item.error_index for item in feedback.items]
        if sorted(returned) != sorted(indices):
            raise ValueError("Feedback items do not match actionable errors")
        for item in feedback.items:
            allowed = {match.chunk.id for match in evidence.get(item.error_index, [])}
            if any(source_id not in allowed for source_id in item.evidence_ids):
                raise ValueError("Feedback cites an evidence ID that was not retrieved")
