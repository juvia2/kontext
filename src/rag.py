from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from google import genai
from google.genai import types

# Chapter 05: these vectors search external grammar notes, not model tokens.

class GeminiEmbedder:
    def __init__(self, client: genai.Client, model: str = 'gemini-embedding-2'):
        self.client = client
        self.model = model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        # One Content per text gives one vector per document.
        contents = [types.Content(parts=[types.Part.from_text(text=text)]) for text in texts]
        response = self.client.models.embed_content(
            model=self.model, contents=contents,
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        embeddings = response.embeddings or []
        if len(embeddings) != len(texts) or any(item.values is None for item in embeddings):
            raise RuntimeError('Gemini returned an unexpected number of embeddings')
        return [list(item.values) for item in embeddings]


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    document_id: str
    title: str
    topic: str
    level: str
    source: str
    source_urls: list[str]
    text: str


@dataclass(frozen=True)
class SearchMatch:
    chunk: KnowledgeChunk
    score: float

    def as_dict(self) -> dict:
        return {"id": self.chunk.id, "document_id": self.chunk.document_id,
                "title": self.chunk.title, "text": self.chunk.text,
                "source": self.chunk.source, "source_urls": self.chunk.source_urls,
                "score": round(self.score, 4)}


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Vectors must be non-empty and have equal dimensions")
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0


def load_chunks(path: str | Path) -> list[KnowledgeChunk]:
    documents = json.loads(Path(path).read_text(encoding="utf-8"))
    chunks: list[KnowledgeChunk] = []
    for doc in documents:
        for index, paragraph in enumerate(doc["content"].split("\n\n"), start=1):
            if paragraph.strip():
                chunks.append(KnowledgeChunk(
                    id=f"{doc['id']}-p{index}", document_id=doc["id"], title=doc["title"],
                    topic=doc["topic"], level=doc["level"], source=doc["source"],
                    source_urls=doc["source_urls"], text=paragraph.strip(),
                ))
    return chunks


class Retriever:
    def __init__(self, chunks: list[KnowledgeChunk], embedder):
        self.chunks = chunks
        self.embedder = embedder
        self._vectors: dict[str, list[list[float]]] = {}

    def retrieve(self, query: str, topic: str, top_k: int = 2) -> list[SearchMatch]:
        topic_chunks = [chunk for chunk in self.chunks if chunk.topic == topic]
        if not topic_chunks:
            return []
        query_text = f"task: search result | query: {query}"
        if topic not in self._vectors:
            documents = [f"title: {chunk.title} | text: {chunk.text}" for chunk in topic_chunks]
            vectors = self.embedder.embed([query_text, *documents])
            if len(vectors) != len(topic_chunks) + 1:
                raise ValueError("Each query and document needs one embedding")
            self._vectors[topic] = vectors[1:]
            query_vector = vectors[0]
        else:
            query_vector = self.embedder.embed([query_text])[0]
        matches = [SearchMatch(chunk, cosine(query_vector, vector))
                   for chunk, vector in zip(topic_chunks, self._vectors[topic])]
        return sorted(matches, key=lambda item: item.score, reverse=True)[:top_k]
