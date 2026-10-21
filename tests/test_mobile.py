from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app
from src.llm import GeminiClient
from src.rag import GeminiEmbedder
from src.llm import LanguageAnalysis


def test_gemini_structured_output_preserves_schema() -> None:
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(output_text='{"utterance":"안녕하세요.","errors":[],"overall_feedback":"좋아요."}')

    client = SimpleNamespace(interactions=SimpleNamespace(create=create))
    result = GeminiClient(client, 'gemini-test').parse(
        'Analyze Korean', {'utterance': '안녕하세요.'}, LanguageAnalysis)
    assert result.utterance == '안녕하세요.'
    assert captured['response_format']['mime_type'] == 'application/json'
    assert 'Analyze Korean' in captured['input']


def test_gemini_embedding_keeps_documents_separate() -> None:
    def embed_content(**kwargs):
        assert len(kwargs['contents']) == 2
        assert all(len(item.parts) == 1 for item in kwargs['contents'])
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 0.0]),
                                           SimpleNamespace(values=[0.0, 1.0])])

    client = SimpleNamespace(models=SimpleNamespace(embed_content=embed_content))
    assert GeminiEmbedder(client).embed(['첫 문서', '둘째 문서']) == [[1.0, 0.0], [0.0, 1.0]]


def test_mobile_serves_page_profile_and_missing_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'mobile.sqlite3'))
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    client = TestClient(app.app)
    assert client.get('/').status_code == 200
    assert 'viewport' in client.get('/').text
    assert client.get('/static/styles.css').status_code == 200
    assert client.get('/api/config').json()['configured'] is False
    assert client.get('/health').status_code == 503
    profile = client.get('/api/profile', params={'learner_id': 'demo-test'}).json()
    assert profile['profile']['recent_patterns']['connective_ending'] == 3
    response = client.post('/api/analyze', json={'learner_id': 'demo-test', 'utterance': '안녕하세요.'})
    assert response.status_code == 503
    assert 'GEMINI_API_KEY' in response.json()['detail']
    assert client.get('/api/profile', params={'learner_id': '../bad'}).status_code == 422


def test_mobile_analyze_returns_pipeline_and_profile(monkeypatch, tmp_path) -> None:
    from test_pipeline import FakeAnalyzer, FakeEmbedder, FakeGenerator, ROOT
    from src.rag import Retriever, load_chunks

    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'mobile.sqlite3'))
    monkeypatch.setenv('GEMINI_API_KEY', 'offline-test-key')
    monkeypatch.setenv('DEMO_HOURLY_LIMIT', '1')
    app.recent_requests.clear()
    retriever = Retriever(load_chunks(ROOT / 'data' / 'grammar.json'), FakeEmbedder())
    monkeypatch.setattr(app, 'model_resources', lambda _: (FakeAnalyzer(), retriever, FakeGenerator()))
    client = TestClient(app.app)
    assert client.get('/health').status_code == 200
    response = client.post('/api/analyze', json={
        'learner_id': 'demo-test', 'utterance': '이미 먹었어서 카페에 갔어요.',
    })
    assert response.status_code == 200
    data = response.json()
    assert data['analysis']['errors'][0]['expression'] == '먹었어서'
    assert data['evidence']['0'][0]['document_id'] == 'ending-eoseo'
    assert data['tool_results'][0]['status'] == 'updated'
    assert data['profile']['recent_patterns']['connective_ending'] == 4
    assert any(step['name'] == 'Tool Results' for step in data['trace']['steps'])
    assert client.post('/api/analyze', json={'learner_id': 'demo-test', 'utterance': '안녕하세요.'}).status_code == 429
