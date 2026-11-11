from __future__ import annotations

import json

from fakes import ROOT, FakeEmbedder, make_settings

from src.rag import Retriever, cosine, load_entries, make_chunks
from src.schemas import Category

ENTRIES = load_entries(ROOT / "data" / "grammar.json")


def test_grammar_entries_are_complete():
    ids = [entry.id for entry in ENTRIES]
    assert len(ids) == len(set(ids)) and len(ids) >= 50
    categories = {category.value for category in Category}
    assert {entry.category for entry in ENTRIES} == categories   # 모든 범주에 자료가 있다
    for entry in ENTRIES:
        assert entry.rule and entry.examples and len(entry.errors) >= 1, entry.id
        assert entry.source_url.startswith("https://krdict.korean.go.kr/"), entry.id
        for error in entry.errors:
            assert error["wrong"] != error["right"] and error["why"], entry.id


def test_evaluation_cases_point_at_real_text_and_entries():
    ids = {entry.id: entry.category for entry in ENTRIES}
    cases = json.loads((ROOT / "data" / "evaluation_cases.json").read_text(encoding="utf-8"))
    assert len({case["id"] for case in cases}) == len(cases) >= 40
    for case in cases:
        for expected in case["expect"]:
            assert expected["expression"] in case["utterance"], case["id"]
            assert ids[expected["grammar_id"]] == expected["category"], case["id"]
        for optional in case.get("optional", []):
            assert optional in case["utterance"], case["id"]


def test_entry_is_split_into_rule_errors_contrast():
    entry = next(e for e in ENTRIES if e.id == "p-object")
    assert [c.kind for c in make_chunks([entry])] == ["rule", "errors", "contrast"]


def test_search_finds_the_entry_and_respects_threshold(tmp_path):
    retriever = Retriever(ENTRIES, FakeEmbedder(), make_settings(tmp_path))
    result = retriever.search_many([("조사 | 책이 → 책을 | 문장: 어제 책이 읽었어요.", "particle")])[0]
    assert result.matches[0].entry.id == "p-object" and len(result.matches) <= 2
    strict = Retriever(ENTRIES, FakeEmbedder(), make_settings(tmp_path, evidence_min_score=0.99))
    result = strict.search_many([("조사 | 책이 → 책을", "particle")])[0]
    assert result.matches == [] and len(result.rejected) == 1


def test_document_vectors_are_cached_on_disk(tmp_path):
    first = FakeEmbedder()
    Retriever(ENTRIES, first, make_settings(tmp_path), cache_dir=tmp_path).search_many([("책이 → 책을", "particle")])
    assert first.calls == 2 and len(list(tmp_path.glob("embeddings-*.json"))) == 1
    second = FakeEmbedder()
    Retriever(ENTRIES, second, make_settings(tmp_path), cache_dir=tmp_path).search_many([("책이 → 책을", "particle")])
    assert second.calls == 1   # 문서는 파일에서 읽고 질문만 임베딩한다


def test_cosine():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0 and cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_evaluation_scoring():
    from evaluate import score_case, summarize

    case = {"id": "x", "utterance": "어제 책이 읽었어요. 근데 좋아요.",
            "expect": [{"expression": "책이", "category": "particle", "grammar_id": "p-object"}], "optional": ["근데"]}
    finding = lambda index, start, end, expression, **extra: {
        "index": index, "start": start, "end": end, "expression": expression, "suggestion": "-", "actionable": True,
        "category": "particle", "evidence": [], "record": None, **extra}
    payload = {"overall": "", "question": None, "trace": {"latency_ms": 10}, "findings": [
        finding(0, 3, 5, "책이", evidence=[{"id": "p-object", "score": 0.8}], record={"status": "saved"}),
        finding(1, 12, 14, "근데"),      # optional: 오탐으로 세지 않는다
        finding(2, 15, 18, "좋아요"),    # 기대에 없는 교정: 오탐
    ]}
    scored = score_case(case, payload)
    assert scored["missed"] == [] and scored["false_positives"] == ["좋아요"]
    summary = summarize([scored, {"id": "y", "failure": "x"}])
    assert summary["detection_recall"] == 1.0 and summary["detection_precision"] == 0.5
    assert summary["retrieval_hit_rate"] == 1.0 and summary["failed_runs"] == 1
    assert summary["lowest_top_score_among_hits"] == 0.8
