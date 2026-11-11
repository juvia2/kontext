from __future__ import annotations

import pytest
from fakes import FakeModel, analysis_for, make_pipeline, tutor_for

from src.llm import ModelError, build_analysis, locate
from src.pipeline import PipelineFailure, apply_corrections, build_query, sentence_around
from src.schemas import AnalysisOutput, Candidate, ProfileUpdateCall

SENTENCE = "어제 책이 읽었어요. 근데 정말 재미있었어요."


def test_full_flow_cites_evidence_and_saves(tmp_path):
    pipeline, repository, model = make_pipeline(tmp_path)
    result = pipeline.run("tester", SENTENCE)
    payload = result.as_payload({"p-object": "을/를: 동작의 대상"})
    finding = payload["findings"][0]
    assert finding["expression"] == "책이" and finding["actionable"]
    assert finding["evidence"][0]["id"] == "p-object" and finding["evidence"][0]["cited"]
    assert finding["record"]["status"] == "saved" and finding["seen_count"] == 1
    assert payload["corrected"] == "어제 책을 읽었어요. 근데 정말 재미있었어요."
    assert "answer_index" not in payload["question"]
    assert [s["key"] for s in payload["trace"]["steps"]] == [
        "input", "profile", "analysis", "retrieval", "generation", "tools"]
    assert payload["trace"]["model_calls"] == 2
    assert repository.get_profile("tester").grammar_counts == {"p-object": 1}
    assert model.calls == ["AnalysisOutput", "TutorOutput"]


def test_acceptable_expression_is_shown_but_not_corrected(tmp_path):
    pipeline, _, _ = make_pipeline(tmp_path)
    findings = pipeline.run("tester", SENTENCE).as_payload({})["findings"]
    casual = next(f for f in findings if f["expression"] == "근데")
    assert casual["judgment"] == "acceptable" and not casual["actionable"]
    assert casual["evidence"] == [] and casual["record"] is None


def test_clean_sentence_skips_search_and_second_model_call(tmp_path):
    pipeline, repository, model = make_pipeline(tmp_path)
    result = pipeline.run("tester", "어제 친구와 영화를 봤어요.")
    statuses = {s["key"]: s["status"] for s in result.trace.steps}
    assert statuses["retrieval"] == statuses["generation"] == "skipped"
    assert result.question is None and model.calls == ["AnalysisOutput"]
    assert repository.stats("tester") == {"sentences": 1, "corrections": 0,
                                           "practice_total": 0, "practice_correct": 0}


def test_repeat_is_counted_from_saved_history(tmp_path):
    pipeline, _, _ = make_pipeline(tmp_path)
    pipeline.run("tester", SENTENCE)
    second = pipeline.run("tester", "오늘도 책이 읽었어요.")
    assert second.seen_counts == {0: 2}
    context = next(s for s in second.trace.steps if s["key"] == "generation")["data"]["context"]
    assert context["evidence"]["0"][0]["times_recorded"] == 1


def test_bad_candidates_are_dropped_not_fatal():
    output = AnalysisOutput(summary="확인", candidates=[
        Candidate(expression="없는말", occurrence=1, category="word", judgment="error",
                  suggestion="다른말", explanation="x", confidence=0.9),
        Candidate(expression="읽었어요", occurrence=1, category="tense", judgment="error",
                  suggestion="읽었어요", explanation="x", confidence=0.9),
        Candidate(expression="책이", occurrence=1, category="particle", judgment="error",
                  suggestion="책을", explanation="x", confidence=0.5),
        Candidate(expression="책이 읽었어요", occurrence=1, category="particle", judgment="error",
                  suggestion="책을 읽었어요", explanation="x", confidence=0.9),
    ])
    analysis = build_analysis("어제 책이 읽었어요.", output, 0.6)
    assert [d["reason"] for d in analysis.dropped] == ["원문에 없는 표현", "바꿀 내용이 없는 교정", "다른 후보와 겹침"]
    assert len(analysis.findings) == 1 and not analysis.findings[0].actionable  # 확신도 0.5 < 0.6


def test_tool_proposals_are_validated_before_saving(tmp_path):
    def tutor(context):
        output = tutor_for(context)
        output.tool_calls = [
            ProfileUpdateCall(index=0, grammar_id="s-doe", reason="근거에 없는 자료"),
            ProfileUpdateCall(index=7, grammar_id="p-object", reason="없는 번호"),
            ProfileUpdateCall(index=0, grammar_id="p-object", reason="정상"),
            ProfileUpdateCall(index=0, grammar_id="p-object", reason="중복"),
        ]
        return output

    pipeline, repository, _ = make_pipeline(tmp_path, FakeModel(tutor=tutor))
    result = pipeline.run("tester", SENTENCE)
    assert [(r.status, r.reason) for r in result.tool_results] == [
        ("rejected", "검색된 근거에 없는 문법 자료"), ("rejected", "없는 표현 번호"),
        ("saved", "학습 기록에 저장함"), ("rejected", "같은 표현을 두 번 제안함")]
    assert repository.stats("tester")["corrections"] == 1


def test_low_confidence_gets_feedback_but_no_record(tmp_path):
    def analysis(utterance):
        output = analysis_for(utterance)
        output.candidates[0].confidence = 0.7
        return output

    pipeline, repository, _ = make_pipeline(tmp_path, FakeModel(analysis=analysis))
    result = pipeline.run("tester", SENTENCE)
    assert result.items[0].explanation
    assert result.tool_results[0].reason == "확신도가 기록 기준보다 낮음"
    assert repository.stats("tester")["corrections"] == 0


def test_no_evidence_above_threshold_means_no_citation_and_no_record(tmp_path):
    pipeline, repository, _ = make_pipeline(tmp_path, evidence_min_score=0.99)
    result = pipeline.run("tester", SENTENCE)
    retrieval = next(s for s in result.trace.steps if s["key"] == "retrieval")["data"][0]
    assert retrieval["matches"] == [] and retrieval["rejected"][0]["id"]
    assert result.evidence == {0: []} and result.tool_results == []
    assert result.question.grammar_id == ""
    assert repository.stats("tester")["corrections"] == 0


def test_sloppy_model_output_is_repaired(tmp_path):
    def tutor(context):
        output = tutor_for(context)
        output.items[0].index = 5                     # 없는 번호
        output.question.grammar_id = "made-up"        # 검색되지 않은 자료
        return output

    pipeline, _, _ = make_pipeline(tmp_path, FakeModel(tutor=tutor))
    result = pipeline.run("tester", SENTENCE)
    repairs = next(s for s in result.trace.steps if s["key"] == "generation")["data"]["repairs"]
    assert len(repairs) == 3
    assert result.items[0].explanation == "'읽다'의 대상에는 '을'을 써요."  # 분석 단계의 설명으로 대체
    assert result.question.grammar_id == ""


def test_model_failure_is_reported_with_trace(tmp_path):
    def broken(_):
        raise ModelError("모델을 2번 호출했지만 쓸 수 있는 응답을 받지 못했습니다 (ValidationError)")

    events = []
    pipeline, repository, _ = make_pipeline(tmp_path, FakeModel(analysis=broken))
    with pytest.raises(PipelineFailure) as failure:
        pipeline.run("tester", SENTENCE, events.append)
    steps = failure.value.trace.steps
    assert [(s["key"], s["status"]) for s in steps] == [("input", "ok"), ("profile", "ok"), ("analysis", "failed")]
    assert "2번 호출" in steps[-1]["message"]
    assert events[0] == {"type": "start", "key": "input"} and events[-1]["step"]["status"] == "failed"
    assert repository.stats("tester")["sentences"] == 0


def test_empty_and_too_long_input(tmp_path):
    pipeline, _, _ = make_pipeline(tmp_path)
    for text in ("   ", "가" * 501):
        with pytest.raises(PipelineFailure) as failure:
            pipeline.run("tester", text)
        assert failure.value.trace.steps[0]["status"] == "failed"


def test_practice_answer_is_checked_on_the_server_once(tmp_path):
    pipeline, repository, _ = make_pipeline(tmp_path)
    request_id = pipeline.run("tester", SENTENCE).trace.request_id
    assert repository.answer_practice("tester", request_id, 9) is None
    assert repository.answer_practice("someone-else", request_id, 1) is None
    first = repository.answer_practice("tester", request_id, 0)
    assert first == {"correct": False, "answer_index": 1, "explanation": "'보다'의 대상이라서 '를'이에요."}
    repository.answer_practice("tester", request_id, 1)  # 두 번째 답은 기록을 바꾸지 않는다
    stats = repository.stats("tester")
    assert (stats["practice_total"], stats["practice_correct"]) == (1, 0)
    assert repository.history("tester")[0]["practice_correct"] == 0


def test_text_helpers():
    text = "저는 책이 좋아요. 그래서 책이 읽었어요."
    assert locate(text, "책이", 2) == text.rindex("책이")
    assert locate(text, "책이", 5) == text.index("책이")
    assert sentence_around(text, text.rindex("책이")) == "그래서 책이 읽었어요."
    analysis = build_analysis(text, AnalysisOutput(summary="s", candidates=[
        Candidate(expression="책이", occurrence=2, category="particle", judgment="error",
                  suggestion="책을", explanation="x", confidence=0.9),
        Candidate(expression="좋아요", occurrence=1, category="word", judgment="less_natural",
                  suggestion="좋아해요", explanation="x", confidence=0.9)]), 0.6)
    assert apply_corrections(text, analysis.findings) == "저는 책이 좋아요. 그래서 책을 읽었어요."
    assert build_query(text, analysis.findings[1]) == "조사 | 책이 → 책을 | 문장: 그래서 책이 읽었어요."
