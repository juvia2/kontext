"""설정과 판단 기준을 한곳에 모은 파일.

숫자 기준(확신도, 검색 점수)은 여기에서만 정한다. 다른 파일과 프롬프트는 이 값을 받아서 쓴다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    embedding_model: str
    database_path: Path
    # 모델이 스스로 매긴 확신도(0~1)가 이 값 이상인 오류·덜 자연스러운 표현만 피드백 대상으로 삼는다.
    feedback_min_confidence: float
    # 학습 기록에 남기려면 이 값 이상이어야 한다. 피드백 기준보다 높게 둔다.
    record_min_confidence: float
    # 검색된 문법 자료의 유사도가 이 값보다 낮으면 근거로 쓰지 않는다.
    evidence_min_score: float
    # 모델이 붙인 범주와 같은 범주의 자료에 더하는 가산점.
    category_bonus: float
    # 표현 하나에 붙이는 근거 자료의 최대 개수.
    top_k: int
    # 학습자 한 명이 한 시간에 요청할 수 있는 분석 횟수.
    hourly_limit: int
    # 모델 응답이 형식 검사를 통과하지 못했을 때 다시 요청하는 횟수.
    retries: int

    @property
    def ready(self) -> bool:
        return bool(self.api_key)


def load_settings(getenv=os.getenv) -> Settings:
    database = Path(getenv("DATABASE_PATH", "data/kontext.sqlite3"))
    return Settings(
        api_key=getenv("GEMINI_API_KEY", ""),
        model=getenv("TUTOR_MODEL", "gemini-3.5-flash-lite"),
        embedding_model=getenv("EMBEDDING_MODEL", "gemini-embedding-2"),
        database_path=database if database.is_absolute() else ROOT / database,
        feedback_min_confidence=float(getenv("FEEDBACK_MIN_CONFIDENCE", "0.6")),
        record_min_confidence=float(getenv("RECORD_MIN_CONFIDENCE", "0.75")),
        evidence_min_score=float(getenv("EVIDENCE_MIN_SCORE", "0.73")),
        category_bonus=float(getenv("CATEGORY_BONUS", "0.03")),
        top_k=int(getenv("EVIDENCE_TOP_K", "2")),
        hourly_limit=int(getenv("DEMO_HOURLY_LIMIT", "20")),
        retries=int(getenv("MODEL_RETRIES", "1")),
    )
