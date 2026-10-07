from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from src.llm import Analyzer
from src.llm import GeminiClient
from src.llm import Generator
from src.rag import GeminiEmbedder
from src.rag import Retriever, load_chunks

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')


@dataclass(frozen=True)
class ModelSettings:
    api_key: str
    model: str
    embedding_model: str

    @property
    def ready(self) -> bool:
        return bool(self.api_key)


def settings(getenv=os.getenv) -> ModelSettings:
    return ModelSettings(
        api_key=getenv('GEMINI_API_KEY', ''),
        model=getenv('TUTOR_MODEL', 'gemini-3.5-flash-lite'),
        embedding_model=getenv('EMBEDDING_MODEL', 'gemini-embedding-2'),
    )


def build_model_resources(config: ModelSettings) -> tuple[Analyzer, Retriever, Generator]:
    if not config.ready:
        raise ValueError('GEMINI_API_KEY is required')
    api = genai.Client(api_key=config.api_key)
    structured = GeminiClient(api, config.model)
    retriever = Retriever(
        load_chunks(ROOT / 'data' / 'grammar.json'),
        GeminiEmbedder(api, config.embedding_model),
    )
    return Analyzer(structured), retriever, Generator(structured)
