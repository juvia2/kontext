from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fakes import ROOT, FakeEmbedder, FakeModel, make_settings
from fastapi.testclient import TestClient

import app
from src.llm import Analyzer, GeminiClient, Generator, ModelError
from src.rag import GeminiEmbedder, Retriever, load_entries
from src.schemas import AnalysisOutput

SENTENCE = "어제 책이 읽었어요."
VALID = '{"candidates": [], "summary": "좋아요."}'


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("GEMINI_API_KEY", "offline")
    monkeypatch.setenv("DEMO_HOURLY_LIMIT", "2")
    app.limiter.clear()
    settings = make_settings(tmp_path)
    model = FakeModel()
    retriever = Retriever(load_entries(ROOT / "data" / "grammar.json"), FakeEmbedder(), settings)
    monkeypatch.setattr(app, "resources", lambda _: (Analyzer(model, settings), retriever, Generator(model)))
    return TestClient(app.app)


def stream(client, utterance, learner="demo-a"):
    response = client.post("/api/analyze", json={"learner_id": learner, "utterance": utterance})
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines()]


def test_page_and_static_files(client):
    assert client.get("/").status_code == 200 and "viewport" in client.get("/").text
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/health").json() == {"ok": True, "configured": True}


def test_analyze_streams_steps_then_result(client):
    events = stream(client, SENTENCE)
    assert events[0] == {"type": "start", "key": "input"}
    assert [e["step"]["key"] for e in events if e["type"] == "step"] == [
        "input", "profile", "analysis", "retrieval", "generation", "tools"]
    result = events[-1]
    assert result["type"] == "result" and result["findings"][0]["record"]["status"] == "saved"
    assert result["stats"]["corrections"] == 1 and result["patterns"][0]["grammar_id"] == "p-object"
    assert result["history"][0]["utterance"] == SENTENCE
    answer = client.post("/api/practice", json={"learner_id": "demo-a", "request_id": result["request_id"],
                                                "choice_index": 1}).json()
    assert answer["correct"] is True
    assert client.get("/api/profile", params={"learner_id": "demo-a"}).json()["stats"]["practice_correct"] == 1


def test_new_learner_starts_empty_and_can_set_profile(client):
    data = client.get("/api/profile", params={"learner_id": "demo-new"}).json()
    assert data["history"] == [] and data["patterns"] == [] and data["stats"]["sentences"] == 0
    updated = client.put("/api/profile", json={"learner_id": "demo-new", "level": "A2", "native_language": "영어"})
    assert updated.json()["profile"]["level"] == "A2"
    assert client.put("/api/profile", json={"learner_id": "demo-new", "level": "C9",
                                            "native_language": ""}).status_code == 422
    assert client.get("/api/profile", params={"learner_id": "../bad"}).status_code == 422


def test_rate_limit_is_per_learner_and_failures_are_refunded(client, monkeypatch):
    stream(client, SENTENCE)
    stream(client, SENTENCE)
    blocked = client.post("/api/analyze", json={"learner_id": "demo-a", "utterance": SENTENCE})
    assert blocked.status_code == 429
    assert stream(client, SENTENCE, "demo-b")[-1]["type"] == "result"     # 다른 학습자는 영향 없음

    def broken(_):
        raise ModelError("실패")

    monkeypatch.setattr(app, "resources", lambda _: (SimpleNamespace(analyze=lambda *a: broken(a)), None, None))
    for _ in range(3):   # 실패는 한도를 쓰지 않으므로 한도 2회를 넘겨도 429가 아니다
        events = stream(client, SENTENCE, "demo-c")
        assert events[-1]["type"] == "error" and events[-1]["trace"]["steps"][-1]["status"] == "failed"


def test_missing_key_and_empty_input(client, monkeypatch):
    assert client.post("/api/analyze", json={"learner_id": "demo-a", "utterance": "  "}).status_code == 422
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setattr(app, "load_settings", lambda: make_settings(ROOT, api_key=""))
    assert client.post("/api/analyze", json={"learner_id": "demo-a", "utterance": SENTENCE}).status_code == 503


def test_gemini_request_shape_and_retry():
    captured = []
    replies = iter(["not json", VALID])

    def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(output_text=next(replies))

    model = GeminiClient(SimpleNamespace(interactions=SimpleNamespace(create=create)), "gemini-test", retries=1)
    output, attempts = model.parse("지시문", {"utterance": "안녕하세요."}, AnalysisOutput)
    assert attempts == 2 and output.summary == "좋아요."
    request = captured[0]
    assert request["system_instruction"] == "지시문" and "지시문" not in request["input"]
    assert request["response_format"]["mime_type"] == "application/json"
    assert request["generation_config"] == {"temperature": 0} and request["store"] is False

    always_bad = SimpleNamespace(interactions=SimpleNamespace(create=lambda **_: SimpleNamespace(output_text="{}")))
    with pytest.raises(ModelError):
        GeminiClient(always_bad, "gemini-test", retries=1).parse("지시문", {}, AnalysisOutput)


def test_embedder_sends_one_content_per_text():
    def embed_content(**kwargs):
        assert all(len(content.parts) == 1 for content in kwargs["contents"])
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 0.0]) for _ in kwargs["contents"]])

    client = SimpleNamespace(models=SimpleNamespace(embed_content=embed_content))
    assert len(GeminiEmbedder(client, "embed-test").embed([f"문서 {i}" for i in range(120)])) == 120
