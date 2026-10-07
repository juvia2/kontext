from __future__ import annotations

import logging
import os
import re
import time
from collections import deque
from threading import Lock
from contextlib import closing
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.learner import LearnerRepository, connect
from src.services import ModelSettings, build_model_resources, settings
from src.pipeline import PipelineFailure, TutorPipeline

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
app = FastAPI(title='Kontext', version='1.0.0')
app.mount('/static', StaticFiles(directory=WEB), name='static')
LEARNER_ID = re.compile(r'^[a-zA-Z0-9_-]{1,80}$')
recent_requests: deque[float] = deque()
request_lock = Lock()


class AnalysisRequest(BaseModel):
    learner_id: str = Field(min_length=1, max_length=80)
    utterance: str = Field(min_length=1, max_length=2000)


def validate_learner_id(value: str) -> str:
    if not LEARNER_ID.fullmatch(value):
        raise HTTPException(status_code=422, detail='올바른 학습자 ID가 필요합니다.')
    return value


def reserve_demo_request() -> None:
    limit = int(os.getenv('DEMO_HOURLY_LIMIT', '20'))
    with request_lock:
        now = time.monotonic()
        while recent_requests and recent_requests[0] < now - 3600:
            recent_requests.popleft()
        if len(recent_requests) >= limit:
            raise HTTPException(status_code=429, detail='데모 사용 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.')
        recent_requests.append(now)


def db_path() -> Path:
    value = os.getenv('DATABASE_PATH', 'data/tutor.sqlite3')
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


@lru_cache(maxsize=2)
def model_resources(config: ModelSettings):
    return build_model_resources(config)


@app.get('/', include_in_schema=False)
def index():
    return FileResponse(WEB / 'index.html')


@app.get('/api/config')
def config():
    model = settings()
    return {'provider': 'gemini', 'model': model.model,
            'configured': model.ready, 'key_name': 'GEMINI_API_KEY'}


@app.get('/health')
def health():
    if not settings().ready:
        raise HTTPException(status_code=503, detail='GEMINI_API_KEY가 필요합니다.')
    return {'ok': True}


@app.get('/api/profile')
def profile(learner_id: str = Query(min_length=1, max_length=80)):
    validate_learner_id(learner_id)
    with closing(connect(db_path())) as connection:
        repo = LearnerRepository(connection)
        repo.ensure_learner(learner_id)
        repo.seed_demo_history(learner_id)
        return {'profile': repo.get_profile(learner_id).as_context(),
                'history': repo.recent_history(learner_id, 5)}


@app.post('/api/analyze')
def analyze(request: AnalysisRequest):
    validate_learner_id(request.learner_id)
    if not request.utterance.strip():
        raise HTTPException(status_code=422, detail='한국어 발화를 입력해 주세요.')
    model = settings()
    if not model.ready:
        raise HTTPException(status_code=503, detail='GEMINI_API_KEY를 .env에 설정해 주세요.')
    reserve_demo_request()
    try:
        analyzer, retriever, generator = model_resources(model)
        with closing(connect(db_path())) as connection:
            repo = LearnerRepository(connection)
            repo.ensure_learner(request.learner_id)
            repo.seed_demo_history(request.learner_id)
            result = TutorPipeline(repo, analyzer, retriever, generator).run(
                request.learner_id, request.utterance)
            return {
                'analysis': result.analysis.model_dump(mode='json'),
                'feedback': result.feedback.model_dump(mode='json'),
                'practice': result.practice.model_dump(mode='json'),
                'evidence': {str(index): [TutorPipeline._match_dict(match) for match in matches]
                             for index, matches in result.evidence.items()},
                'tool_results': [item.as_dict() for item in result.tool_results],
                'trace': result.trace.as_dict(),
                'profile': repo.get_profile(request.learner_id).as_context(),
                'history': repo.recent_history(request.learner_id, 5),
            }
    except PipelineFailure as exc:
        logging.exception('Pipeline failed, request_id=%s', exc.trace.request_id)
        raise HTTPException(status_code=502, detail={
            'message': '분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.',
            'trace': exc.trace.as_dict(),
        }) from exc
    except Exception as exc:
        logging.exception('Model connection failed')
        raise HTTPException(status_code=502, detail='모델 연결에 실패했습니다. 서버 설정을 확인해 주세요.') from exc
