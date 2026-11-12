"""문법 자료 검색(RAG의 Retrieval).

data/grammar.json의 항목을 청크로 나누고, 검색용 임베딩으로 바꾼 뒤, 학습자의 표현과 가장 가까운
항목을 찾는다. 여기서 쓰는 벡터는 문서를 찾기 위한 검색 임베딩이며 Gemini 내부의 토큰 임베딩이 아니다.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from src.config import Settings


@dataclass(frozen=True)
class GrammarEntry:
    id: str
    category: str
    title: str
    level: str
    rule: str
    examples: tuple[str, ...]
    errors: tuple[dict, ...]
    contrast: str
    source_name: str
    source_url: str

    def as_context(self) -> dict:
        """모델에 근거로 넘기는 내용."""
        return {"id": self.id, "title": self.title, "rule": self.rule,
                "examples": list(self.examples), "errors": list(self.errors), "contrast": self.contrast}


@dataclass(frozen=True)
class Chunk:
    """검색 단위. 항목 하나가 규칙 / 오류 사례 / 구분 기준 청크로 나뉜다."""
    entry_id: str
    kind: str
    text: str


@dataclass(frozen=True)
class Match:
    entry: GrammarEntry
    score: float
    kind: str  # 어느 청크가 가장 가까웠는지

    def as_dict(self) -> dict:
        return {"id": self.entry.id, "title": self.entry.title, "category": self.entry.category,
                "rule": self.entry.rule, "example": self.entry.examples[0] if self.entry.examples else "",
                "source_name": self.entry.source_name, "source_url": self.entry.source_url,
                "score": round(self.score, 3), "matched": self.kind}


@dataclass(frozen=True)
class SearchResult:
    query: str
    matches: list[Match]    # 기준을 넘은 근거
    rejected: list[Match]   # 가장 가까웠지만 기준에 못 미친 것(과정 표시용)


def load_entries(path: str | Path) -> list[GrammarEntry]:
    entries = []
    for item in json.loads(Path(path).read_text(encoding="utf-8")):
        entries.append(GrammarEntry(
            id=item["id"], category=item["category"], title=item["title"], level=item["level"],
            rule=item["rule"], examples=tuple(item["examples"]), errors=tuple(item["errors"]),
            contrast=item.get("contrast", ""),
            source_name=item["source"]["name"], source_url=item["source"]["url"],
        ))
    return entries


def make_chunks(entries: Sequence[GrammarEntry]) -> list[Chunk]:
    """항목을 뜻이 다른 세 부분으로 나눈다.

    - rule: 규칙과 올바른 예문
    - errors: 학습자가 자주 틀리는 문장과 고친 문장
    - contrast: 헷갈리는 표현과의 구분
    """
    chunks: list[Chunk] = []
    for entry in entries:
        chunks.append(Chunk(entry.id, "rule", f"{entry.rule} 예: {' '.join(entry.examples)}"))
        if entry.errors:
            pairs = " / ".join(f"{e['wrong']} → {e['right']} ({e['why']})" for e in entry.errors)
            chunks.append(Chunk(entry.id, "errors", f"자주 틀리는 문장: {pairs}"))
        if entry.contrast:
            chunks.append(Chunk(entry.id, "contrast", entry.contrast))
    return chunks


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("벡터는 비어 있지 않고 차원이 같아야 합니다")
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0


class GeminiEmbedder:
    BATCH = 50

    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        from google.genai import types  # 테스트에서는 가짜 임베더를 쓰므로 여기서 불러온다

        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self.BATCH):
            batch = texts[offset:offset + self.BATCH]
            # 텍스트마다 Content를 하나씩 만들어야 텍스트마다 벡터가 하나씩 나온다.
            contents = [types.Content(parts=[types.Part.from_text(text=text)]) for text in batch]
            response = self.client.models.embed_content(
                model=self.model, contents=contents,
                # 무료 등급은 분당 100텍스트라 청크 146개를 한 번에 못 넣는다. 429면 분 단위로 기다렸다 다시 보낸다.
                config=types.EmbedContentConfig(
                    output_dimensionality=768,
                    http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(
                        attempts=3, initial_delay=30, max_delay=60, http_status_codes=[429, 503])),
                ),
            )
            embeddings = response.embeddings or []
            if len(embeddings) != len(batch) or any(item.values is None for item in embeddings):
                raise RuntimeError("임베딩 개수가 요청한 텍스트 개수와 다릅니다")
            vectors.extend(list(item.values) for item in embeddings)
        return vectors


class Retriever:
    def __init__(self, entries: Sequence[GrammarEntry], embedder: Any, settings: Settings,
                 cache_dir: Path | None = None):
        self.entries = {entry.id: entry for entry in entries}
        self.chunks = make_chunks(entries)
        self.embedder = embedder
        self.settings = settings
        self.cache_dir = cache_dir
        self._vectors: list[list[float]] | None = None
        self._lock = Lock()

    def _document_vectors(self) -> list[list[float]]:
        """문서 임베딩은 한 번만 계산하고, cache_dir가 있으면 파일로 남겨 재시작 때 다시 쓴다."""
        with self._lock:
            if self._vectors is not None:
                return self._vectors
            documents = [f"title: {self.entries[c.entry_id].title} | text: {c.text}" for c in self.chunks]
            cache_file = None
            if self.cache_dir is not None:
                digest = hashlib.sha256(
                    (getattr(self.embedder, "model", "") + "\n" + "\n".join(documents)).encode("utf-8")
                ).hexdigest()[:16]
                cache_file = self.cache_dir / f"embeddings-{digest}.json"
                if cache_file.exists():
                    self._vectors = json.loads(cache_file.read_text(encoding="utf-8"))
                    return self._vectors
            vectors = self.embedder.embed(documents)
            if len(vectors) != len(documents):
                raise RuntimeError("문서 임베딩 개수가 청크 개수와 다릅니다")
            if cache_file is not None:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(vectors), encoding="utf-8")
            self._vectors = vectors
            return vectors

    def search_many(self, queries: Sequence[tuple[str, str]]) -> list[SearchResult]:
        """(검색 질문, 범주) 여러 개를 한 번의 임베딩 호출로 검색한다."""
        if not queries:
            return []
        document_vectors = self._document_vectors()
        query_vectors = self.embedder.embed([f"task: search result | query: {text}" for text, _ in queries])
        results = []
        for (text, category), query_vector in zip(queries, query_vectors):
            best: dict[str, Match] = {}
            for chunk, vector in zip(self.chunks, document_vectors):
                entry = self.entries[chunk.entry_id]
                score = cosine(query_vector, vector)
                if entry.category == category:
                    score += self.settings.category_bonus
                if chunk.entry_id not in best or score > best[chunk.entry_id].score:
                    best[chunk.entry_id] = Match(entry, score, chunk.kind)
            ranked = sorted(best.values(), key=lambda match: match.score, reverse=True)
            passed = [m for m in ranked if m.score >= self.settings.evidence_min_score][:self.settings.top_k]
            rejected = [] if passed else ranked[:1]
            results.append(SearchResult(text, passed, rejected))
        return results
