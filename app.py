"""웹 요청의 입구. HTTP 요청을 확인해 파이프라인에 넘기고 결과를 돌려준다.

언어 판단이나 검색 규칙은 여기에 없다. src/pipeline.py에서 시작해 읽으면 된다.
"""
from __future__ import annotations

import json
import logging
import queue
import re
import time
from collections import defaultdict, deque
from contextlib import closing
from functools import lru_cache
from threading import Lock, Thread

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config import ROOT, Settings, load_settings
from src.learner import LEVELS, LearnerRepository, connect
from src.pipeline import MAX_LENGTH, PipelineFailure, TutorPipeline, build_resources
from src.rag import load_entries
from src.schemas import CATEGORY_LABELS, JUDGMENT_LABELS, Category, Judgment

WEB = ROOT / "web"
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
app = FastAPI(title="Kontext", version="2.0.0")
app.mount("/static", StaticFiles(directory=WEB), name="static")
LEARNER_ID = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


class RateLimiter:
    """학습자별 시간당 요청 수 제한. 서버 프로세스 하나의 메모리에서만 동작한다."""

    def __init__(self) -> None:
        self.requests: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def reserve(self, key: str, limit: int) -> float:
        with self.lock:
            now = time.monotonic()
            recent = self.requests[key]
            while recent and recent[0] < now - 3600:
                recent.popleft()
            if len(recent) >= limit:
                raise HTTPException(status_code=429, detail="한 시간 사용 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.")
            recent.append(now)
            return now

    def release(self, key: str, stamp: float) -> None:
        """실패한 요청은 한도에서 빼 준다."""
        with self.lock:
            try:
                self.requests[key].remove(stamp)
            except ValueError:
                pass

    def clear(self) -> None:
        with self.lock:
            self.requests.clear()


limiter = RateLimiter()


class AnalyzeRequest(BaseModel):
    learner_id: str = Field(min_length=1, max_length=80)
    utterance: str = Field(min_length=1, max_length=MAX_LENGTH)


class ProfileRequest(BaseModel):
    learner_id: str = Field(min_length=1, max_length=80)
    level: str
    native_language: str = Field(max_length=40)


class PracticeRequest(BaseModel):
    learner_id: str = Field(min_length=1, max_length=80)
    request_id: str = Field(min_length=1, max_length=80)
    choice_index: int = Field(ge=0, le=3)


def check_learner_id(value: str) -> str:
    if not LEARNER_ID.fullmatch(value):
        raise HTTPException(status_code=422, detail="올바른 학습자 ID가 필요합니다.")
    return value


@lru_cache(maxsize=2)
def resources(settings: Settings):
    """모델 연결과 검색기는 설정이 같으면 한 번만 만든다."""
    return build_resources(settings)


@lru_cache(maxsize=1)
def grammar_titles() -> dict[str, str]:
    return {entry.id: entry.title for entry in load_entries(ROOT / "data" / "grammar.json")}


def profile_payload(repo: LearnerRepository, learner_id: str) -> dict:
    profile = repo.get_profile(learner_id)
    titles = grammar_titles()
    history = repo.history(learner_id)
    for row in history:
        row["category_label"] = CATEGORY_LABELS.get(_enum(Category, row["category"]), row["category"])
        row["judgment_label"] = JUDGMENT_LABELS.get(_enum(Judgment, row["judgment"]), row["judgment"])
        row["grammar_title"] = titles.get(row["grammar_id"], "")
    return {
        "profile": {"level": profile.level, "native_language": profile.native_language, "levels": list(LEVELS)},
        "stats": repo.stats(learner_id),
        "patterns": [{"grammar_id": key, "title": titles.get(key, key), "count": count}
                     for key, count in profile.grammar_counts.items()],
        "history": history,
    }


def _enum(kind, value):
    try:
        return kind(value)
    except ValueError:
        return None


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")


@app.get("/health")
def health():
    """서버가 떠 있는지만 알려 준다. 실제 Gemini 연결은 확인하지 않는다."""
    return {"ok": True, "configured": load_settings().ready}


@app.get("/api/config")
def config():
    settings = load_settings()
    return {"configured": settings.ready, "model": settings.model, "max_length": MAX_LENGTH}


@app.get("/api/profile")
def get_profile(learner_id: str = Query(min_length=1, max_length=80)):
    check_learner_id(learner_id)
    with closing(connect(load_settings().database_path)) as connection:
        repo = LearnerRepository(connection)
        repo.ensure_learner(learner_id)
        return profile_payload(repo, learner_id)


@app.put("/api/profile")
def put_profile(request: ProfileRequest):
    check_learner_id(request.learner_id)
    if request.level not in LEVELS:
        raise HTTPException(status_code=422, detail="수준을 다시 선택해 주세요.")
    with closing(connect(load_settings().database_path)) as connection:
        repo = LearnerRepository(connection)
        repo.ensure_learner(request.learner_id)
        repo.set_profile(request.learner_id, request.level, request.native_language.strip())
        return profile_payload(repo, request.learner_id)


@app.post("/api/practice")
def practice(request: PracticeRequest):
    check_learner_id(request.learner_id)
    with closing(connect(load_settings().database_path)) as connection:
        result = LearnerRepository(connection).answer_practice(
            request.learner_id, request.request_id, request.choice_index)
    if result is None:
        raise HTTPException(status_code=404, detail="문제를 찾을 수 없습니다.")
    return result


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest):
    """분석을 실행하며 단계가 끝날 때마다 한 줄씩(JSON Lines) 내려보낸다.

    줄의 type: start(단계 시작) · step(단계 끝) · result(최종 결과) · error(실패).
    """
    check_learner_id(request.learner_id)
    if not request.utterance.strip():
        raise HTTPException(status_code=422, detail="문장을 입력해 주세요.")
    settings = load_settings()
    if not settings.ready:
        raise HTTPException(status_code=503, detail="서버에 GEMINI_API_KEY가 설정되지 않았습니다.")
    stamp = limiter.reserve(request.learner_id, settings.hourly_limit)
    events: queue.Queue[dict | None] = queue.Queue()

    def work() -> None:
        try:
            analyzer, retriever, generator = resources(settings)
            with closing(connect(settings.database_path)) as connection:
                repo = LearnerRepository(connection)
                repo.ensure_learner(request.learner_id)
                pipeline = TutorPipeline(repo, analyzer, retriever, generator, settings)
                result = pipeline.run(request.learner_id, request.utterance, events.put)
                events.put({"type": "result", **result.as_payload(grammar_titles()),
                            **profile_payload(repo, request.learner_id)})
        except PipelineFailure as exc:
            limiter.release(request.learner_id, stamp)
            events.put({"type": "error", "message": "분석을 끝내지 못했어요.", "trace": exc.trace.as_dict()})
        except Exception:
            logging.exception("analyze failed before the pipeline started")
            limiter.release(request.learner_id, stamp)
            events.put({"type": "error", "message": "서버에서 분석을 시작하지 못했어요.", "trace": None})
        finally:
            events.put(None)

    Thread(target=work, daemon=True).start()

    def lines():
        while (event := events.get()) is not None:
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")
