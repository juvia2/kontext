"""실제 Gemini API로 평가 문장을 실행하고 단계별 지표를 낸다.

    python evaluate.py --limit 3            # 먼저 몇 문장만
    python evaluate.py                      # 전체 (문장당 모델 호출 최대 2회)

지표
- 탐지: 고쳐야 할 표현을 찾았는가(재현율), 찾은 것 중 맞는 것의 비율(정밀도)
- 오탐: 고칠 곳이 없는 문장에서 무언가를 고치라고 한 비율
- 범주: 찾은 표현의 범주가 기대와 같은가
- 검색: 기대한 문법 자료가 근거에 들어왔는가, 그때의 유사도 점수
숫자는 보조 지표다. 설명이 타당한지는 reports/의 결과를 사람이 읽고 판단해야 한다.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from src.config import ROOT, load_settings
from src.learner import LearnerRepository, connect
from src.pipeline import PipelineFailure, TutorPipeline, build_resources


def overlaps(utterance: str, expression: str, start: int, end: int) -> bool:
    position = utterance.find(expression)
    return position >= 0 and position < end and start < position + len(expression)


def score_case(case: dict, payload: dict) -> dict:
    utterance = case["utterance"]
    flagged = [f for f in payload["findings"] if f["actionable"]]
    matched, missed, rows = set(), [], []
    for expected in case["expect"]:
        hit = next((f for f in flagged if overlaps(utterance, expected["expression"], f["start"], f["end"])), None)
        if hit is None:
            missed.append(expected["expression"])
            continue
        matched.add(hit["index"])
        evidence_ids = [e["id"] for e in hit["evidence"]]
        rows.append({
            "expression": expected["expression"], "found_as": hit["expression"], "suggestion": hit["suggestion"],
            "category_ok": hit["category"] == expected["category"],
            "evidence_ok": expected["grammar_id"] in evidence_ids,
            "evidence": [(e["id"], e["score"]) for e in hit["evidence"]],
            "recorded": bool(hit["record"] and hit["record"]["status"] == "saved"),
        })
    extra = [f["expression"] for f in flagged if f["index"] not in matched and not any(
        overlaps(utterance, optional, f["start"], f["end"]) for optional in case.get("optional", []))]
    return {"id": case["id"], "utterance": utterance, "expected": len(case["expect"]), "found": rows,
            "missed": missed, "false_positives": extra, "overall": payload["overall"],
            "findings": payload["findings"], "question": payload["question"],
            "latency_ms": payload["trace"]["latency_ms"]}


def summarize(results: list[dict]) -> dict:
    scored = [r for r in results if "failure" not in r]
    expected = sum(r["expected"] for r in scored)
    found = [row for r in scored for row in r["found"]]
    false_positives = sum(len(r["false_positives"]) for r in scored)
    clean = [r for r in scored if r["expected"] == 0]
    ratio = lambda a, b: round(a / b, 3) if b else None
    hit_scores = [score for row in found if row["evidence_ok"] for _, score in row["evidence"][:1]]
    return {
        "cases": len(results), "failed_runs": len(results) - len(scored),
        "detection_recall": ratio(len(found), expected),
        "detection_precision": ratio(len(found), len(found) + false_positives),
        "clean_sentence_false_alarm_rate": ratio(sum(1 for r in clean if r["false_positives"]), len(clean)),
        "category_accuracy": ratio(sum(row["category_ok"] for row in found), len(found)),
        "retrieval_hit_rate": ratio(sum(row["evidence_ok"] for row in found), len(found)),
        "recorded_rate": ratio(sum(row["recorded"] for row in found), len(found)),
        "lowest_top_score_among_hits": min(hit_scores) if hit_scores else None,
        "average_latency_ms": ratio(sum(r["latency_ms"] for r in scored), len(scored)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="평가 문장을 실제 모델로 실행")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "evaluation.json")
    parser.add_argument("--limit", type=int, help="앞에서부터 N문장만 실행")
    parser.add_argument("--min-score", type=float, help="근거 기준 점수를 바꿔서 실행(기준을 정할 때는 0)")
    args = parser.parse_args()
    settings = load_settings()
    if not settings.ready:
        parser.error("GEMINI_API_KEY가 없어 평가를 실행하지 않았습니다")
    if args.min_score is not None:
        settings = replace(settings, evidence_min_score=args.min_score)
    cases = json.loads((ROOT / "data" / "evaluation_cases.json").read_text(encoding="utf-8"))[:args.limit]
    analyzer, retriever, generator = build_resources(settings)
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        connection = connect(Path(temporary) / "evaluation.sqlite3")
        try:
            repository = LearnerRepository(connection)
            pipeline = TutorPipeline(repository, analyzer, retriever, generator, settings)
            for case in cases:
                repository.ensure_learner(case["id"])  # 문장마다 새 학습자: 기록이 서로 섞이지 않는다
                try:
                    results.append(score_case(case, pipeline.run(case["id"], case["utterance"]).as_payload({})))
                except PipelineFailure as exc:
                    results.append({"id": case["id"], "utterance": case["utterance"], "failure": str(exc),
                                    "trace": exc.trace.as_dict()})
                print(".", end="", flush=True)
        finally:
            connection.close()
    report = {"model": settings.model, "embedding_model": settings.embedding_model,
              "evidence_min_score": settings.evidence_min_score, "summary": summarize(results), "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{args.output}")
    for key, value in report["summary"].items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
