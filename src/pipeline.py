"""한 문장이 거치는 여섯 단계의 순서와 실행 기록.

순서는 코드에 정해져 있다(Workflow). 모델은 두 단계에서만 일하고, 나머지는 코드가 한다.
run()을 위에서 아래로 읽으면 전체 흐름이 보인다.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar
from uuid import uuid4

from src.config import ROOT, Settings
from src.learner import LearnerProfile, LearnerRepository, ProfileTools, ToolResult
from src.llm import TOOL_SPECS, Analyzer, GeminiClient, Generator, ModelError
from src.rag import GeminiEmbedder, Match, Retriever, SearchResult, load_entries
from src.schemas import (CATEGORY_LABELS, JUDGMENT_LABELS, Analysis, FeedbackItem, Finding, Judgment,
                         PracticeQuestion, TutorOutput)

T = TypeVar("T")
logger = logging.getLogger("kontext")
MAX_LENGTH = 500

# 단계 이름, 누가 하는 일인지, 어느 파일의 코드인지. 화면의 '분석 과정'이 이 표를 그대로 보여 준다.
STEPS = {
    "input": ("입력 확인", "코드", "src/pipeline.py"),
    "profile": ("학습 기록 읽기", "코드", "src/learner.py"),
    "analysis": ("문장 분석", "모델", "src/llm.py"),
    "retrieval": ("문법 근거 검색", "코드", "src/rag.py"),
    "generation": ("피드백과 문제 생성", "모델", "src/llm.py"),
    "tools": ("검증 후 저장", "코드", "src/learner.py"),
}


@dataclass
class Trace:
    """단계별 실행 기록. on_event가 있으면 단계가 시작하고 끝날 때마다 알린다."""
    on_event: Callable[[dict], None] | None = None
    request_id: str = field(default_factory=lambda: str(uuid4()))
    steps: list[dict[str, Any]] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)

    def _emit(self, event: dict) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def _entry(self, key: str, status: str, start: float | None = None, **extra: Any) -> dict:
        name, who, file = STEPS[key]
        latency = round((time.perf_counter() - start) * 1000, 1) if start is not None else 0.0
        entry = {"key": key, "name": name, "who": who, "file": file, "status": status,
                 "latency_ms": latency, **extra}
        self.steps.append(entry)
        self._emit({"type": "step", "step": entry})
        return entry

    def step(self, key: str, action: Callable[[], T], summarize: Callable[[T], Any] | None = None) -> T:
        self._emit({"type": "start", "key": key})
        start = time.perf_counter()
        try:
            result = action()
        except Exception as exc:
            # 우리가 만든 오류 문구만 화면에 내보내고, 그 밖의 내부 오류는 종류만 남긴다.
            message = str(exc) if isinstance(exc, (ValueError, ModelError)) else f"내부 오류 ({type(exc).__name__})"
            self._entry(key, "failed", start, message=message)
            raise
        self._entry(key, "ok", start, data=summarize(result) if summarize else None)
        return result

    def skip(self, key: str, reason: str) -> None:
        self._entry(key, "skipped", message=reason)

    def as_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id,
                "latency_ms": round((time.perf_counter() - self.started) * 1000, 1),
                "model_calls": sum(1 for s in self.steps if s["who"] == "모델" and s["status"] != "skipped"),
                "steps": self.steps}


class PipelineFailure(RuntimeError):
    def __init__(self, message: str, trace: Trace):
        super().__init__(message)
        self.trace = trace


@dataclass(frozen=True)
class PipelineResult:
    analysis: Analysis
    items: dict[int, FeedbackItem]
    overall: str
    corrected: str
    evidence: dict[int, list[Match]]
    question: PracticeQuestion | None
    tool_results: list[ToolResult]
    seen_counts: dict[int, int]
    trace: Trace

    def as_payload(self, titles: dict[str, str]) -> dict:
        """브라우저로 보내는 JSON. 연습문제의 정답은 넣지 않는다."""
        records = {r.arguments["index"]: r for r in self.tool_results}
        findings = []
        for f in self.analysis.findings:
            item = self.items.get(f.index)
            cited = set(item.evidence_ids) if item else set()
            record = records.get(f.index)
            findings.append({
                **f.model_dump(mode="json"),
                "category_label": CATEGORY_LABELS[f.category],
                "judgment_label": JUDGMENT_LABELS[f.judgment],
                "explanation": item.explanation if item else f.explanation,
                "evidence": [{**m.as_dict(), "cited": m.entry.id in cited} for m in self.evidence.get(f.index, [])],
                "record": {"status": record.status, "reason": record.reason} if record else None,
                "seen_count": self.seen_counts.get(f.index, 0),
            })
        question = None
        if self.question is not None:
            question = {"prompt": self.question.prompt, "choices": self.question.choices,
                        "grammar_title": titles.get(self.question.grammar_id, "")}
        return {"request_id": self.trace.request_id, "utterance": self.analysis.utterance,
                "corrected": self.corrected if self.corrected != self.analysis.utterance else None,
                "overall": self.overall, "findings": findings, "question": question,
                "tool_results": [r.as_dict() for r in self.tool_results], "trace": self.trace.as_dict()}


def sentence_around(text: str, position: int) -> str:
    """position이 들어 있는 문장 하나."""
    start = max((m.end() for m in re.finditer(r"[.!?\n]", text[:position])), default=0)
    end_match = re.search(r"[.!?\n]", text[position:])
    end = position + end_match.end() if end_match else len(text)
    return text[start:end].strip()


def build_query(text: str, finding: Finding) -> str:
    """검색 질문은 모델의 설명이 아니라 학습자의 표현과 그 문장으로 만든다."""
    return (f"{CATEGORY_LABELS[finding.category]} | {finding.expression} → {finding.suggestion} | "
            f"문장: {sentence_around(text, finding.start)}")


def apply_corrections(text: str, findings: list[Finding]) -> str:
    """'오류'로 판단한 표현만 제안으로 바꾼 문장. 뒤에서부터 바꿔야 위치가 밀리지 않는다."""
    for f in sorted(findings, key=lambda item: item.start, reverse=True):
        if f.actionable and f.judgment == Judgment.ERROR:
            text = text[:f.start] + f.suggestion + text[f.end:]
    return text


def repair_output(output: TutorOutput, targets: list[Finding],
                  evidence: dict[int, list[Match]]) -> tuple[dict[int, FeedbackItem], PracticeQuestion, list[str]]:
    """모델 출력이 조금 어긋나도 요청을 실패시키지 않고 바로잡는다. 바로잡은 내용은 기록에 남긴다."""
    notes: list[str] = []
    items: dict[int, FeedbackItem] = {}
    allowed = {f.index: f for f in targets}
    for item in output.items:
        if item.index not in allowed or item.index in items:
            notes.append(f"대상이 아니거나 중복된 피드백 {item.index}번을 버림")
            continue
        retrieved = {m.entry.id for m in evidence.get(item.index, [])}
        kept = [source for source in item.evidence_ids if source in retrieved]
        if len(kept) != len(item.evidence_ids):
            notes.append(f"{item.index}번 피드백에서 검색되지 않은 근거 인용을 지움")
        items[item.index] = FeedbackItem(index=item.index, explanation=item.explanation, evidence_ids=kept)
    for index, finding in allowed.items():
        if index not in items:
            notes.append(f"{index}번 피드백이 없어 분석 단계의 설명을 사용함")
            items[index] = FeedbackItem(index=index, explanation=finding.explanation, evidence_ids=[])
    question = output.question
    if question.grammar_id not in {m.entry.id for matches in evidence.values() for m in matches}:
        if question.grammar_id:
            notes.append("문제의 문법 자료 id가 검색 결과에 없어 비움")
        question = question.model_copy(update={"grammar_id": ""})
    return items, question, notes


class TutorPipeline:
    def __init__(self, repository: LearnerRepository, analyzer: Analyzer, retriever: Retriever,
                 generator: Generator, settings: Settings):
        self.repository = repository
        self.analyzer = analyzer
        self.retriever = retriever
        self.generator = generator
        self.settings = settings
        self.tools = ProfileTools(repository, settings)

    def run(self, learner_id: str, utterance: str, on_event: Callable[[dict], None] | None = None) -> PipelineResult:
        trace = Trace(on_event)
        try:
            # 1. 입력 확인 (코드)
            text = trace.step("input", lambda: self._validate(utterance), lambda value: {"length": len(value)})

            # 2. 이번 요청 이전의 학습 기록 읽기 (코드)
            profile = trace.step("profile", lambda: self.repository.get_profile(learner_id),
                                 lambda value: value.as_context())

            # 3. 모델 호출 1: 살펴볼 표현 고르기. 코드가 후보를 걸러 Finding으로 만든다.
            analysis = trace.step("analysis", lambda: self.analyzer.analyze(text, profile.level),
                                  lambda value: value.model_dump(mode="json"))
            targets = [f for f in analysis.findings if f.actionable]

            if not targets:
                # 고칠 표현이 없으면 검색과 두 번째 모델 호출을 하지 않는다.
                trace.skip("retrieval", "피드백할 표현이 없어 검색하지 않음")
                trace.skip("generation", "피드백할 표현이 없어 모델을 다시 호출하지 않음")
                trace.step("tools", lambda: self.repository.save_attempt(trace.request_id, learner_id, text, text),
                           lambda _: {"attempt_saved": True, "results": []})
                return PipelineResult(analysis, {}, analysis.summary, text, {}, None, [], {}, trace)

            # 4. 표현마다 문법 근거 검색 (코드). 기준 점수를 넘지 못하면 근거 없이 진행한다.
            searches = trace.step(
                "retrieval",
                lambda: self.retriever.search_many([(build_query(text, f), f.category.value) for f in targets]),
                lambda value: [self._search_summary(f, s) for f, s in zip(targets, value)])
            evidence = {f.index: s.matches for f, s in zip(targets, searches)}

            # 5. 모델 호출 2: 원문 + 분석 + 학습 기록 + 근거 → 피드백, 문제, 도구 호출 제안
            context = self._context(text, profile, targets, evidence)
            generated = trace.step("generation", lambda: self._generate(context, targets, evidence),
                                   lambda value: {"attempts": value["attempts"], "repairs": value["repairs"],
                                                  "context": context,
                                                  "output": value["output"].model_dump(mode="json")})
            output: TutorOutput = generated["output"]
            corrected = apply_corrections(text, analysis.findings)

            # 6. 도구 호출 제안을 검사하고, 통과한 것만 저장 (코드)
            tool_results = trace.step(
                "tools",
                lambda: self._save(trace.request_id, learner_id, text, corrected, output, generated["question"],
                                   analysis, evidence),
                lambda value: {"attempt_saved": True, "proposed": [c.model_dump() for c in output.tool_calls],
                               "results": [r.as_dict() for r in value]})
            seen = {r.arguments["index"]: profile.grammar_counts.get(r.arguments["grammar_id"], 0) + 1
                    for r in tool_results if r.status == "saved"}
            return PipelineResult(analysis, generated["items"], output.overall, corrected, evidence,
                                  generated["question"], tool_results, seen, trace)
        except Exception as exc:
            logger.exception("pipeline failed request_id=%s", trace.request_id)
            raise PipelineFailure(str(exc), trace) from exc
        finally:
            logger.info("request_id=%s steps=%s", trace.request_id,
                        [(s["key"], s["status"], s["latency_ms"]) for s in trace.steps])

    @staticmethod
    def _validate(utterance: str) -> str:
        text = utterance.strip()
        if not text:
            raise ValueError("문장을 입력해 주세요.")
        if len(text) > MAX_LENGTH:
            raise ValueError(f"입력은 {MAX_LENGTH}자까지 쓸 수 있습니다.")
        return text

    @staticmethod
    def _search_summary(finding: Finding, search: SearchResult) -> dict:
        return {"index": finding.index, "expression": finding.expression, "query": search.query,
                "matches": [m.as_dict() for m in search.matches],
                "rejected": [m.as_dict() for m in search.rejected]}

    def _context(self, text: str, profile: LearnerProfile, targets: list[Finding],
                 evidence: dict[int, list[Match]]) -> dict:
        """두 번째 모델 호출의 입력(Augmented Context)."""
        return {
            "utterance": text,
            "learner": {"level": profile.level, "native_language": profile.native_language},
            "findings": [f.model_dump(mode="json", exclude={"start", "end", "actionable"}) for f in targets],
            "evidence": {str(index): [{**m.entry.as_context(),
                                       "times_recorded": profile.grammar_counts.get(m.entry.id, 0)}
                                      for m in matches]
                         for index, matches in evidence.items()},
            "tools": TOOL_SPECS,
            "record_min_confidence": self.settings.record_min_confidence,
        }

    def _generate(self, context: dict, targets: list[Finding], evidence: dict[int, list[Match]]) -> dict:
        output, attempts = self.generator.respond(context)
        items, question, repairs = repair_output(output, targets, evidence)
        return {"output": output, "attempts": attempts, "items": items, "question": question, "repairs": repairs}

    def _save(self, request_id: str, learner_id: str, text: str, corrected: str, output: TutorOutput,
              question: PracticeQuestion, analysis: Analysis, evidence: dict[int, list[Match]]) -> list[ToolResult]:
        self.repository.save_attempt(request_id, learner_id, text, corrected)
        results = self.tools.execute(learner_id=learner_id, request_id=request_id, calls=output.tool_calls,
                                     analysis=analysis, evidence=evidence)
        self.repository.save_practice(request_id, learner_id, question)
        return results


def build_resources(settings: Settings) -> tuple[Analyzer, Retriever, Generator]:
    """실제 Gemini에 연결된 분석기, 검색기, 생성기를 만든다."""
    from google import genai

    if not settings.ready:
        raise ValueError("GEMINI_API_KEY가 필요합니다")
    api = genai.Client(api_key=settings.api_key)
    model = GeminiClient(api, settings.model, settings.retries)
    retriever = Retriever(load_entries(ROOT / "data" / "grammar.json"),
                          GeminiEmbedder(api, settings.embedding_model), settings,
                          cache_dir=ROOT / "data" / ".cache")
    return Analyzer(model, settings), retriever, Generator(model)
