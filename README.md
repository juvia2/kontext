# Kontext — 코드를 열어 볼 수 있는 한국어 학습 LLM 데모

Kontext는 「LLM.zip | 압축 해제」 시리즈의 마지막 실습입니다. 모바일 화면에서 한국어 문장을 입력하면 표현 분석, 관련 문법 검색, 개인화 피드백, 객관식 문제, 학습 기록 갱신을 실행합니다. **이 프로젝트의 목적은 결과 화면을 보는 데서 끝나지 않고, 처음 보는 사람이 코드로 LLM 시스템의 연결 구조를 이해하는 것**입니다. Python에 익숙하지 않거나 에이전트가 만든 코드를 뜯어보는 독자를 위해 파일 수와 실행 경로를 작게 유지했습니다.

**코드 해설을 먼저 읽고 싶다면 → [CODE_GUIDE.md](CODE_GUIDE.md)**

이 문서에는 폴더를 나눈 이유, 실제 파이프라인, 파일별 주요 함수, 필요한 Python 배경지식, 시리즈 챕터와 코드의 연결을 한곳에 정리했습니다.

## 무엇을 직접 확인할 수 있나요?

1. **문장 연습** 탭에 자유로운 한국어 문장을 입력합니다. `틀린 문장`과 `일상 문장` 버튼으로 예시를 불러올 수도 있습니다.
2. 입력 바로 아래에서 분석과 피드백을 보고, 생성된 문제 한 개를 풉니다. 오류 후보가 없으면 문제와 새 오류 기록을 만들지 않습니다.
3. **학습 기록** 탭에서 이전 오류 패턴과 최근 기록을 봅니다. 처음 표시되는 5건은 개인화 과정을 보여 주기 위한 예시 기록입니다.
4. 결과 아래 **분석 과정 보기**를 펼쳐 입력, 모델 분석, 문법 검색, 생성 Context, 저장 제안, 실제 저장 결과와 단계별 소요 시간을 비교합니다.

문장과 정답이 코드에 고정되어 있지 않습니다. `data/evaluation_cases.json`의 8문장은 모델을 평가하기 위한 표본이고, 앱의 입력 가능 문장 목록이 아닙니다. 모델은 문맥에 따라 `error`, `less_natural`, `acceptable`, `uncertain`을 구분하도록 요청받으므로 같은 표현도 다른 판단이 나올 수 있습니다.

## LLM 모델과 이 앱이 맡는 일

```text
사용자 문장
  ↓
Gemini: 구조화된 문장 분석
  ↓
앱: 이전 학습 기록 + 검색한 문법 근거를 Context에 결합
  ↓
Gemini: 피드백 + 문제 1개 + 기록 갱신 제안
  ↓
앱: 제안 검증 → 조건을 만족할 때만 SQLite 저장
  ↓
모바일 화면 + 분석 과정 보기
```

Gemini 내부의 토큰화·Attention·Transformer·학습 과정은 API 뒤에 있습니다. 이 저장소는 모델을 직접 학습하지 않고 **추론을 호출하는 시스템**을 구현합니다. `src/rag.py`의 벡터는 외부 문법 자료를 찾기 위한 **검색 임베딩**입니다. RAG는 검색 결과를 생성 입력에 더하는 흐름이며, 별도 Vector DB가 있어야만 가능한 기능은 아닙니다. 모델의 `profile_updates`는 **저장 제안**이고 실제 DB 쓰기는 Python 코드가 검증한 뒤 실행합니다. 실행 순서는 정해져 있으므로 자율 Agent가 아닌 Workflow입니다.

## 폴더 구조

```text
app.py                  FastAPI 화면·API 입구
src/llm.py              출력 형식, Gemini 호출, 분석·생성
src/rag.py              문법 자료 청킹·임베딩·유사도 검색
src/learner.py          SQLite 학습 기록과 저장 제안 검증
src/pipeline.py         전체 단계의 순서와 실행 기록
data/                   문법 자료 24개와 평가 문장 8개
web/                    모바일 화면 HTML·CSS·JS
tests/                  실제 API 없이 흐름을 확인하는 테스트
evaluate.py             실제 Gemini API 평가 도구
CODE_GUIDE.md           처음 보는 사람을 위한 전체 코드 해설
Procfile                Railway 웹 서버 실행 명령
```

`src/`는 **모델·검색·학습자 상태·실행 순서**만 분리했습니다. 별도 프런트엔드 프레임워크, LangChain, Vector DB, Docker 설정은 없습니다. `src/__init__.py`는 Python 패키지 표시용 빈 파일입니다. 로컬 `.env`, `.venv`, 생성된 SQLite 파일은 Git에 포함되지 않습니다.

Uvicorn은 설치된 웹 서버 라이브러리이며 그 내부 코드를 이 저장소에 넣지 않았습니다. `Procfile`의 한 줄로 실행합니다. Streamlit으로 화면을 다시 만들 수도 있지만, 이 프로젝트는 모바일 화면과 분석 과정 표시를 위해 현재의 작은 FastAPI API와 정적 웹 화면을 사용합니다.

## 블로그 시리즈와 함께 읽는 순서

| 개념 | 코드에서 볼 곳 |
| --- | --- |
| 00~04. 언어가 숫자로 처리되고 모델이 추론하는 과정 | `src/llm.py`의 모델 호출; 내부 토큰화와 Transformer는 API 뒤에 있음을 확인 |
| 01·02. 벡터·임베딩 | `src/rag.py`의 `GeminiEmbedder`와 `cosine()`; 검색 임베딩과 모델 내부 임베딩을 구분 |
| 05. RAG | `data/grammar.json` → `src/rag.py` → `src/pipeline.py`의 Context |
| 06. Tool Calling과 Agent | `src/learner.py`의 `ProfileTools`; 제안과 실행을 분리한 Workflow |
| 07. Final | `app.py` → `src/pipeline.py` → `web/`의 결과·분석 과정 보기 |

챕터별로 어떤 함수까지 읽으면 되는지, 한 문장이 실제로 어떤 데이터를 거쳐 돌아오는지는 [코드 해설](CODE_GUIDE.md#6-블로그-챕터와-연결하기)에 있습니다. [블로그 시리즈 README](https://velog.io/@olivia02/LLM-%EA%B8%B0%EC%88%A0-%EC%8A%A4%ED%83%9D-%EB%BF%8C%EC%8B%9C%EA%B8%B0-README)와 나란히 읽을 수 있습니다.

## 로컬에서 실행

Python 3.12 기준입니다. 프로젝트 루트에서 실행합니다.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env`에 본인의 [Google AI Studio Gemini API 키](https://aistudio.google.com/apikey)를 입력합니다. **키를 채팅이나 GitHub에 올리지 마세요.** 기본 모델을 바꾸지 않는다면 필요한 값은 키 하나입니다.

```dotenv
GEMINI_API_KEY=여기에_본인의_키
```

`.env.example`의 `TUTOR_MODEL`, `EMBEDDING_MODEL`, `DATABASE_PATH`, `DEMO_HOURLY_LIMIT`는 바꿀 수 있는 기본값을 보여 줍니다. 현재 기본 모델은 `gemini-3.5-flash-lite`, 검색 임베딩은 `gemini-embedding-2`입니다. 모델별 무료 사용 범위와 계정별 한도는 바뀔 수 있으므로 [공식 가격표](https://ai.google.dev/gemini-api/docs/pricing)와 [AI Studio 사용 한도](https://ai.google.dev/gemini-api/docs/rate-limits)를 확인하세요.

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

브라우저에서 `http://127.0.0.1:8000`을 엽니다. 키 없이도 입력 화면과 예시 학습 기록은 열리지만 실제 문장 분석은 실행되지 않습니다. 휴대폰에서 같은 와이파이로 확인할 때에는 서버를 `--host 0.0.0.0`으로 시작하고 컴퓨터의 로컬 IP로 접속합니다.

## 테스트와 실제 모델 평가

```bash
python -m pytest -q
python evaluate.py --limit 1 --output reports/smoke.json
python evaluate.py --output reports/evaluation.json
```

첫 명령은 가짜 모델·가짜 임베딩으로 코드를 검사합니다. 뒤의 두 명령은 **실제 Gemini API를 호출**하므로 먼저 한 문장만 확인한 뒤 전체 8건을 실행합니다. 평가 도구는 감지한 오류 범주와 검색 문서, 피드백, 저장 결과, 실행 기록을 JSON으로 남깁니다. 자동 범주 일치 개수는 보조 지표이며 한국어 교정의 타당성은 사람이 확인해야 합니다.

## Railway에 배포

이 저장소는 모바일 웹과 API를 **FastAPI 서버 하나**에서 제공합니다. Railway의 Python 빌더가 `requirements.txt`와 `.python-version`을 읽고, `Procfile`이 `uvicorn app:app --host 0.0.0.0 --port $PORT`를 실행합니다. 별도 Dockerfile은 필요하지 않습니다. Railway는 `$PORT`를 주입하며, 웹 서버가 그 포트에서 들어오는 요청을 받아야 합니다. [Railway FastAPI 배포 안내](https://docs.railway.com/guides/fastapi) · [포트 안내](https://docs.railway.com/networking/troubleshooting/application-failed-to-respond)

1. 변경 내용을 **직접 커밋·푸시**한 뒤 Railway에서 **New Project → Deploy from GitHub repo**를 선택하고 이 저장소의 `master`를 연결합니다.
2. 서비스의 **Variables**에 `GEMINI_API_KEY`를 입력합니다. 키 값은 저장소의 `.env`가 아닌 Railway에만 둡니다. 필요하면 `TUTOR_MODEL`, `EMBEDDING_MODEL`, `DEMO_HOURLY_LIMIT`도 설정합니다. [Railway 변수 안내](https://docs.railway.com/variables)
3. 학습 기록을 재배포 뒤에도 유지하려면 서비스에 **Volume을 `/data`로 마운트**하고 `DATABASE_PATH=/data/tutor.sqlite3`를 설정합니다. 볼륨을 연결하지 않으면 SQLite 기록은 임시 상태입니다. **`/app/data`에는 볼륨을 마운트하지 마세요.** 그 경로에는 배포에 필요한 `grammar.json`이 있습니다. [Railway 볼륨 안내](https://docs.railway.com/volumes)
4. 서비스 설정에서 Healthcheck 경로를 `/health`로 지정할 수 있습니다. 이 경로는 키 설정 여부만 확인하므로 실제 Gemini 연결은 다음 단계에서 따로 시험해야 합니다. [Railway 헬스체크 안내](https://docs.railway.com/deployments/healthchecks)
5. 배포 상태가 정상인 것을 확인한 뒤 **Settings → Networking → Generate Domain**으로 공개 주소를 만듭니다. 휴대폰에서 `/` 화면을 열고, `/health`가 200인지 확인한 다음 예시 문장 하나를 분석합니다. [Railway 공개 도메인 안내](https://docs.railway.com/guides/fastapi)

Railway 무료 체험은 기간·크레딧 제한이 있고, **Limited Trial의 외부 네트워크 제한**은 Gemini 호출을 막을 수 있습니다. Free 플랜에도 월별 크레딧 한도가 있으므로 배포 전 계정의 플랜과 예상 사용량을 확인하세요. [Railway 무료 체험](https://docs.railway.com/pricing/free-trial) · [플랜](https://docs.railway.com/pricing/plans)

## 데이터와 운영 범위

`data/grammar.json`의 24개 요약은 국립국어원 [한국어기초사전](https://krdict.korean.go.kr/) 항목을 참고해 직접 작성했고, 각 항목에 참고 링크가 있습니다. 사전 전체나 학습자 말뭉치를 내려받은 자료가 아닙니다. 출처와 이용 조건은 [코드 해설의 자료 출처](CODE_GUIDE.md#자료-출처)에서 확인할 수 있습니다.

브라우저의 학습자 ID는 임의로 만들어져 해당 브라우저에 저장됩니다. 로그인·인증 기능이 아니며, 처음 5건의 기록은 데모 시드입니다. 서버의 기본 시간당 20회 제한도 단일 프로세스 메모리에서만 작동합니다. 기록을 장기 보존하거나 실제 이용자 계정을 운영하려면 인증, 강한 사용량 제한, 영속 저장소와 개인정보 처리가 추가로 필요합니다. 학습 문장은 Gemini API로 전송되므로 실명 등 민감한 정보를 넣지 마세요. 무료 등급 데이터 처리 조건은 [Google 공식 가격표](https://ai.google.dev/gemini-api/docs/pricing)를 확인하세요.

이 데모의 검색 자료와 모델 결과가 모든 한국어 표현의 정답을 보장하지는 않습니다. 문법 근거의 유사도는 검색 순위이며 오류 확률이 아닙니다. 모델 confidence 역시 자체 추정치입니다. API 호출에 실패하면 피드백이 생성되지 않고, 실패 단계는 분석 과정 기록과 서버 로그에서 확인할 수 있습니다.
