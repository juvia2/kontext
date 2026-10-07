from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from src.learner import connect
from src.learner import LearnerRepository
from src.services import build_model_resources, settings
from src.pipeline import PipelineFailure, TutorPipeline


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run actual API evaluation on the curated demo cases")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "evaluation.json")
    parser.add_argument("--limit", type=int, help="Evaluate only the first N cases for a quick live check")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    load_dotenv(ROOT / ".env")
    config = settings()
    if not config.ready:
        parser.error("GEMINI_API_KEY is required; no model evaluation was run")
    analyzer, retriever, generator = build_model_resources(config)
    model_name, embedding_model = config.model, config.embedding_model
    cases = json.loads((ROOT / "data" / "evaluation_cases.json").read_text(encoding="utf-8"))
    if args.limit is not None:
        cases = cases[:args.limit]
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        connection = connect(Path(temporary) / "evaluation.sqlite3")
        try:
            repository = LearnerRepository(connection)
            pipeline = TutorPipeline(repository, analyzer, retriever, generator)
            for case in cases:
                repository.ensure_learner(case["id"])
                repository.seed_demo_history(case["id"])
                try:
                    result = pipeline.run(case["id"], case["utterance"])
                    categories = sorted({error.category.value for error in result.analysis.errors
                                         if error.judgment.value in ("error", "less_natural")})
                    documents = sorted({match.chunk.document_id for matches in result.evidence.values()
                                        for match in matches})
                    results.append({
                        "id": case["id"], "input": case["utterance"], "expected_categories": case["expected_categories"],
                        "detected_errors": [error.model_dump(mode="json") for error in result.analysis.errors],
                        "retrieved_knowledge": documents, "generated_feedback": result.feedback.model_dump(mode="json"),
                        "tool_result": [item.as_dict() for item in result.tool_results],
                        "category_match": any(set(categories) == set(allowed) for allowed in
                                              case.get("allowed_category_sets", [case["expected_categories"]])),
                        "expected_evidence_present": (set(case["expected_evidence"]).issubset(documents)
                                                       if categories else None),
                        "trace": result.trace.as_dict(),
                    })
                except PipelineFailure as exc:
                    results.append({"id": case["id"], "input": case["utterance"], "failure": str(exc),
                                    "trace": exc.trace.as_dict()})
        finally:
            connection.close()
    report = {"model": model_name, "embedding_model": embedding_model, "results": results,
              "category_matches": sum(item.get("category_match", False) for item in results),
              "case_count": len(results)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}: {report['category_matches']}/{report['case_count']} exact category matches")


if __name__ == "__main__":
    main()
