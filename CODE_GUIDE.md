# Kontext 코드 해설: LLM 시스템을 처음부터 따라 읽기

이 문서는 Kontext를 만들지 않은 사람이 코드를 열어 **입력이 어디로 가고, 모델이 무엇을 반환하며, 어떤 코드가 결과를 검증·저장하는지** 따라가기 위한 지도입니다. Python 문법에 익숙하지 않아도 파일을 읽는 순서와 핵심 함수부터 확인할 수 있도록 작성했습니다. 실행 방법과 Railway 배포 방법은 [README.md](README.md)에 있습니다.

Kontext는 한국어 문장을 교정하는 모바일 웹 데모입니다. 동시에 「LLM.zip | 압축 해제」의 마지막 실습으로, **완성된 LLM을 호출하는 부분**과 **그 주위에서 학습 기록·문법 자료·도구 실행을 관리하는 애플리케이션 부분**을 보여줍니다. 이 저장소는 모델을 직접 학습시키거나 Transformer 내부를 구현하지 않습니다.

## 1. 먼저 볼 큰 그림

```text
브라우저의 한국어 문장
    ↓
app.py: 입력 확인, API 키 확인, 요청 제한, DB 연결
    ↓
src/pipeline.py: 단계의 순서를 결정
    ├─ src/learner.py: 이전 학습 기록 읽기
    ├─ src/llm.py: Gemini로 문장 분석 → 정해진 JSON 형식 확인
    ├─ src/rag.py: 관련 문법 자료를 검색
    ├─ src/llm.py: 분석 + 기록 + 근거로 피드백과 문제 생성
    └─ src/learner.py: 모델의 기록 제안을 검증한 뒤 SQLite에 저장
    ↓
web/: 피드백, 문제, 학습 기록, 단계별 실행 기록 표시
```

여기서 **LLM 모델**은 Gemini API 뒤에 있습니다. 토큰화, 모델 내부 임베딩, Attention, Transformer 연산은 이 앱에서 보거나 수정할 수 없습니다. 이 프로젝트가 직접 구현한 것은 API 호출을 연결하는 **LLM 시스템**입니다. `src/rag.py`의 임베딩은 문법 문서를 찾기 위한 별도의 검색 벡터이며 모델 내부의 토큰 임베딩이 아닙니다.

Uvicorn의 내부 실행 코드는 이 저장소에 복사되어 있지 않습니다. `Procfile`은 설치된 Uvicorn 패키지로 `app.py`의 서버를 시작하는 한 줄짜리 명령입니다. 학습할 코드는 `src/`의 파이프라인과 `app.py`의 연결 부분입니다. 화면은 이미 모바일용 HTML·CSS·JS로 만들어져 있으므로, Streamlit 예시 코드로 바꾸면 현재 화면과 API 흐름도 다시 만들어야 합니다.

## 2. 이 폴더 구조를 선택한 이유

```text
Kontext/
├── README.md              프로젝트 소개·실행·Railway 배포
├── CODE_GUIDE.md          지금 읽는 코드 해설
├── app.py                 브라우저와 Python 파이프라인의 접점
├── evaluate.py            예시 문장으로 실제 모델 평가
├── Procfile               Railway에서 웹 서버를 켜는 명령
├── requirements.txt       설치할 Python 패키지
├── .python-version        Python 버전
├── .env.example           환경 변수 이름의 예시 (실제 키 없음)
├── .gitignore             키·가상환경·생성 파일을 Git에서 제외
├── src/
│   ├── __init__.py        Python 패키지 표시용 빈 파일
│   ├── llm.py             출력 형식, Gemini 호출, 분석·생성
│   ├── rag.py             문법 자료 청킹·임베딩·검색
│   ├── learner.py         SQLite 학습 기록과 저장 제안 검증
│   └── pipeline.py        위 기능을 호출하는 순서와 실행 기록
├── data/
│   ├── grammar.json       출처가 표시된 문법 요약 24개
│   └── evaluation_cases.json  직접 작성한 평가 문장 8개
├── web/
│   ├── index.html         모바일 화면의 구조
│   ├── styles.css         화면 디자인
│   └── app.js             버튼, API 요청, 결과 표시
└── tests/
    ├── test_pipeline.py   검색·생성·저장 Workflow 검사
    └── test_mobile.py     모바일 API와 Gemini 호출 형식 검사
```

`src/`의 네 파일은 **모델·검색·상태·실행 순서**라는 네 가지 책임에 대응합니다. 하나로 합치면 모델의 답변과 실제 DB 저장 코드가 뒤섞이고, 더 잘게 쪼개면 파일 사이를 지나치게 자주 이동해야 합니다. 화면은 빌드 도구 없이 HTML/CSS/JS 세 파일로 구성하고, 서버는 `app.py` 하나가 제공합니다. `tests/`는 처음 읽을 때 건너뛰어도 되지만, 코드를 바꾼 뒤 기존 흐름이 유지되는지 확인할 때 사용합니다. `src/__init__.py`는 Python이 `src`를 패키지로 다루도록 남겨 둔 빈 파일입니다.

처음 읽는 순서는 **`app.py`의 `/api/analyze` → `src/pipeline.py`의 `run()` → `src/llm.py` → `src/rag.py` → `src/learner.py` → `web/app.js`**를 권합니다. `data/`와 `tests/`는 각 단계가 궁금할 때 열면 됩니다.

## 3. 한 문장이 이동하는 실제 경로

예를 들어 사용자가 `어제 책이 읽었어요.`를 입력한다고 가정합니다. 아래 교정 내용은 **가능한 흐름을 설명하기 위한 예시**이며, 앱에 고정된 답변은 아닙니다.

| 순서 | 코드 위치 | 무엇이 들어가고 나오는가 |
| --- | --- | --- |
| 1 | `web/app.js` | 문장과 브라우저의 데모 학습자 ID를 `/api/analyze`로 보냅니다. |
| 2 | `app.py`의 `analyze()` | ID·빈 입력·길이·API 키·시간당 요청 수를 확인하고 SQLite 연결을 엽니다. 새 ID에는 예시 학습 기록 5건을 넣습니다. |
| 3 | `src/pipeline.py`의 `run()` | `LearnerRepository.get_profile()`로 **이번 요청 이전의** 오류 패턴을 읽습니다. |
| 4 | `src/llm.py`의 `Analyzer.analyze()` | Gemini가 `LanguageAnalysis` 형식으로 오류 후보, 판단, 제안, 자신이 추정한 확신도를 반환합니다. 예를 들어 `책이` → `책을`을 제안할 수 있습니다. |
| 5 | `src/pipeline.py`의 `actionable()` | `error` 또는 `less_natural`이고 confidence가 0.65 이상인 후보만 다음 검색 대상으로 고릅니다. |
| 6 | `src/rag.py`의 `Retriever.retrieve()` | 후보 범주의 문법 요약을 벡터로 비교하고 유사도 상위 2개를 가져옵니다. 검색 결과에는 문서 ID, 문장, 출처가 있습니다. |
| 7 | `src/pipeline.py`의 `_context()` | 원문 + 분석 결과 + 이전 기록 + 검색 근거를 하나의 입력 데이터로 묶습니다. |
| 8 | `src/llm.py`의 `Generator.respond()` | Gemini가 피드백, 객관식 문제 **1개**, `profile_updates` 저장 제안을 정해진 형식으로 만듭니다. |
| 9 | `src/pipeline.py`와 `src/learner.py` | 인용한 근거 ID와 저장 제안을 검사합니다. 조건을 만족한 제안만 `error_history`에 기록합니다. |
| 10 | `app.py` → `web/app.js` | 분석, 피드백, 문제, 검색 근거, 도구 결과, 단계별 실행 기록을 화면에 표시합니다. |

중간에 오가는 자료는 아래 세 덩어리로 기억하면 됩니다. `LanguageAnalysis`의 `errors[]`는 모델의 **분석 후보**, `Augmented Context`는 **그 후보 + 이전 기록 + 검색 문서**, `TutorResponse`의 `profile_updates[]`는 **DB에 쓰기 전의 제안**입니다. 실제 저장 여부는 `ToolResult.status`가 알려 줍니다. 모델이 분석한 후보가 곧바로 저장되는 구조가 아닙니다.

처음 분석에서 수정할 후보가 없다면 6·8단계의 검색과 두 번째 Gemini 호출을 건너뜁니다. 피드백의 전체 평가는 첫 분석 결과를 사용하고, 연습문제와 새 오류 기록은 만들지 않습니다. 이것은 `run()`의 `if indices:` 분기에서 확인할 수 있습니다.

## 4. 주요 파일의 코드 구조

### `app.py` — 웹 요청의 입구

- `GET /`: `web/index.html`을 보여줍니다. `/static`에는 CSS·JS를 연결합니다.
- `GET /api/config`: 브라우저에 **키 값 없이** 모델 연결 가능 여부를 알려줍니다.
- `GET /health`: `GEMINI_API_KEY`가 없으면 503, 있으면 200을 반환합니다. 실제 Gemini 호출 성공까지 검사하는 경로는 아닙니다.
- `GET /api/profile`: 데모 학습자 ID의 수준, 반복 오류와 최근 5건을 읽습니다.
- `POST /api/analyze`: 입력을 확인하고 `TutorPipeline.run()`을 호출한 뒤 결과를 JSON으로 돌려줍니다.
- `db_path()`: 로컬 기본값 `data/tutor.sqlite3` 또는 `DATABASE_PATH` 환경 변수를 사용합니다.
- `reserve_demo_request()`: 서버 프로세스에서 기본 시간당 20회의 분석을 제한합니다. 재시작하면 카운터가 초기화되므로 계정별 사용량 관리 기능은 아닙니다.

`app.py`에는 언어 판단이나 문법 검색 규칙을 넣지 않았습니다. HTTP 요청을 Python 기능에 연결하는 역할만 보이게 한 것입니다.

### `src/llm.py` — 모델에 무엇을 요청하고 어떤 형태로 받을까?

파일 앞부분의 Pydantic 클래스는 JSON의 **모양과 기본 제약**입니다. `LanguageAnalysis.errors`는 여러 오류 후보를 담고, `Judgment`는 문법 오류(`error`), 문맥상 덜 자연스러움(`less_natural`), 허용 가능(`acceptable`), 판단 보류(`uncertain`)를 구분합니다. `FeedbackOutput`에는 피드백과 `profile_updates` 제안이 있습니다. `TutorResponse`는 피드백과 문제 한 개를 함께 받아 모델 호출을 줄입니다.

`GeminiClient.parse()`는 지시문과 입력 데이터를 Gemini에 보내고 JSON Schema 형태의 답변을 요청한 뒤 Pydantic으로 검사합니다. `Analyzer.analyze()`는 분석 결과의 원문이 바뀌거나 원문에 없는 표현이 나타나면 거부하고, 원문과 동일한 교정은 제거합니다. `Generator.respond()`는 검색 근거와 학습 기록이 들어 있는 Context로 피드백을 생성합니다. `ModelSettings`, `settings()`, `build_model_resources()`는 키·모델 이름을 읽고 분석기·검색기·생성기를 한 번에 준비합니다.

**JSON 형식을 지켰다는 사실은 문법 판단이 옳다는 뜻이 아닙니다.** 모델의 confidence도 검증된 정답 확률이 아닙니다.

### `src/rag.py`와 `data/` — 외부 문법 지식을 어떻게 찾을까?

`data/grammar.json`의 각 항목에는 `id`, `topic`, `title`, `level`, `content`, `source`, `source_urls`가 있습니다. `load_chunks()`는 `content`를 빈 줄 기준 문단으로 나눕니다. `GeminiEmbedder.embed()`는 각 문단과 검색 질문을 숫자 벡터로 바꿉니다. `Retriever.retrieve()`는 같은 `topic`의 문단을 고르고 `cosine()`으로 유사도를 계산해 상위 결과를 반환합니다. 검색 결과를 화면에 보낼 JSON으로 바꾸는 부분도 `SearchMatch.as_dict()`에 있습니다. 한 범주의 문서 벡터는 첫 검색 후 서버 메모리에서 재사용합니다.

이 과정이 RAG의 **Retrieval**입니다. 검색한 문단을 7단계의 Context에 넣어 피드백을 생성하는 것이 **Augmented Generation**입니다. 별도 Vector DB 없이 작은 자료집을 메모리에서 검색합니다. 검색 유사도는 문서의 순위용 숫자이며 문법 오류의 확률이나 인용 내용의 참을 보장하지 않습니다. 문법 자료 24개는 앱이 받아들이는 입력 문장 24개를 뜻하지 않습니다. 사용자는 자유롭게 문장을 넣을 수 있지만, 자료집이 포괄하는 문법 범위에는 한계가 있습니다.

`data/evaluation_cases.json`의 8문장도 입력 제한 목록이 아닙니다. 모델이 예상 범주와 문서를 찾는지 살펴보기 위해 따로 작성한 예시입니다.

### `src/learner.py` — 모델 밖에 남는 상태와 실제 저장

`connect()`는 SQLite의 `learners`와 `error_history` 테이블을 준비합니다. `LearnerRepository`는 학습자와 기록을 읽고 쓰는 함수들을 묶습니다. 새 브라우저의 데모 ID에는 `seed_demo_history()`가 연결어미 3건·조사 2건을 넣어 개인화 과정을 볼 수 있게 합니다. `get_profile()`은 최근 기록 20건의 범주별 횟수를 반환합니다.

모델은 DB를 직접 수정하지 않습니다. `src/llm.py`가 만든 `profile_updates`는 **제안**일 뿐입니다. `ProfileTools.update_many()`는 오류 번호와 분석 내용이 일치하는지, 판단이 `error`/`less_natural`인지, confidence가 0.75 이상인지, 피드백에서 인용한 검색 근거가 있는지를 확인한 후 저장합니다. 거부·저장·이미 기록됨의 결과가 화면에 표시됩니다. 근거가 있다는 사실만 검사하므로 근거가 언어학적으로 적절한지까지 자동 보증하지는 않습니다.

브라우저의 임의 ID는 로그인 계정이 아닙니다. 기록은 데모용이며 여러 사람이 사용하는 실제 학습 서비스의 인증·개인정보 설계를 대신하지 않습니다.

### `src/pipeline.py` — 누가 다음 단계를 결정할까?

`TutorPipeline.run()`을 위에서 아래로 읽으면 실행 순서가 그대로 보입니다. `PipelineTrace.step()`은 각 단계의 이름, 성공/실패, 소요 시간과 일부 입출력을 기록합니다. 실패하면 `PipelineFailure`가 Trace를 포함해 `app.py`로 돌아갑니다. 화면의 **분석 과정 보기**는 이 Trace를 펼쳐 보여줍니다.

실행 순서는 코드에 미리 정해져 있으므로 이 프로젝트는 **Workflow**입니다. 모델은 도구 사용 여부를 마음대로 결정하는 자율 Agent가 아니고, 앱이 허용한 형식의 저장 제안만 돌려줍니다. 네이티브 Gemini function calling을 호출하지 않습니다. 이 구분 덕분에 **모델의 제안 → 애플리케이션의 검증 → DB 실행** 경계를 직접 확인할 수 있습니다.

### `web/`, `evaluate.py`, `tests/` — 화면과 검증

`web/index.html`은 문장 연습과 학습 기록을 탭으로 나누고, 입력 바로 아래에 결과를 둡니다. `web/app.js`는 `fetch()`로 API를 호출해 피드백·문제·검색 근거·Trace를 안전하게 텍스트로 표시합니다. `web/styles.css`는 모바일 화면의 배치와 색을 담당합니다. 화면 코드는 Gemini 키를 받거나 저장하지 않습니다.

`tests/`는 가짜 모델과 가짜 임베딩을 사용해, 실제 API 비용 없이 정상 흐름·오탐 방지·저장 거부·중복 저장 방지·모바일 API를 확인합니다. `evaluate.py`는 실제 Gemini API로 8개 문장을 실행해 예상 오류 범주와 문법 문서가 나왔는지 보고서를 만듭니다. 그 숫자만으로 피드백의 언어학적 품질을 확정할 수는 없습니다.

## 5. Python 코드가 낯설다면

| 코드 모양 | 이 프로젝트에서 읽는 방법 |
| --- | --- |
| `from src.llm import Analyzer` | 다른 파일에서 `Analyzer`를 가져옵니다. 이동 경로를 따라 읽을 때 쓰입니다. |
| `class ...` | 관련 데이터나 동작을 한 이름 아래 묶습니다. `LearnerRepository`는 DB 읽기·쓰기 함수의 묶음입니다. |
| `def ...` | 하나의 작업을 수행하는 함수입니다. `run()`은 여러 함수를 순서대로 호출합니다. |
| `BaseModel` / `Field` | Pydantic이 모델 응답 JSON의 필드와 길이·값 범위를 확인합니다. |
| `@dataclass` | 단순한 데이터를 담는 클래스를 짧게 선언합니다. 검색 결과와 학습자 프로필에 사용합니다. |
| `with self.connection:` | DB 쓰기 중 오류가 나면 변경을 되돌리는 트랜잭션 범위입니다. |
| `@lru_cache` | 같은 설정으로 만든 모델 연결·검색기를 다시 사용합니다. |
| `dict`, `list`, `str`, `float` | 타입 힌트입니다. 읽는 사람과 도구에 예상 데이터 모양을 알려줍니다. |

에이전트와 함께 코드를 읽을 때는 한 번에 전체 구현을 설명해 달라고 하기보다 `TutorPipeline.run()`의 **한 단계가 어느 파일의 어느 함수로 이어지는지** 물어보면 확인하기 쉽습니다. 모델 답변이 이상하다면 `src/llm.py`의 지시문과 JSON 형식, 근거가 이상하다면 `data/grammar.json`과 `src/rag.py`, 기록이 이상하다면 `src/learner.py`의 검증 조건부터 보세요.

## 6. 블로그 챕터와 연결하기

| 시리즈의 개념 | 이 코드에서 확인할 곳 | 직접 구현한 범위 |
| --- | --- | --- |
| 00. LLM의 전체 흐름 | 이 문서의 1·3절, `src/llm.py` | 이미 학습된 Gemini에 입력을 보내고 출력을 받습니다. |
| 01. Vector와 유사도 연산 | `src/rag.py`의 `cosine()` | 검색 벡터의 내적·크기를 계산합니다. |
| 02. Tokenization과 Embedding | `src/rag.py`의 `GeminiEmbedder` | **검색용** 임베딩을 호출합니다. 모델 내부 토큰화는 구현하지 않습니다. |
| 03. Attention과 Transformer | 이 문서의 1절 | 모델 내부 연산은 Gemini API 뒤에 있음을 구분합니다. |
| 04. Training과 Inference | `src/llm.py`의 `GeminiClient` | 재학습 없이 학습된 모델을 추론에 사용합니다. |
| 05. RAG | `data/grammar.json`, `src/rag.py`, `src/pipeline.py` | 자료를 검색하고 생성 Context에 넣습니다. |
| 06. Tool Calling과 Agent | `src/learner.py`의 `ProfileTools` | 구조화된 **저장 제안**을 앱이 검증해 실행합니다. 자율 Agent는 아닙니다. |
| 07. Final | `src/pipeline.py`, `app.py`, `web/` | 모든 단계를 모바일 앱에서 연결하고 Trace로 보여줍니다. |

이 실습에서 꼭 분리해서 기억할 것은 네 가지입니다: **모델 내부 임베딩과 검색 임베딩**, **RAG와 Vector DB**, **모델의 도구 제안과 실제 실행**, **정해진 Workflow와 자율 Agent**.

## 7. 직접 확인할 때 볼 것과 한계

1. 문장을 입력하고 **분석 과정 보기**를 엽니다. `Structured Language Analysis`의 판단과 `Retrieved Knowledge`의 문서 ID·유사도를 비교합니다.
2. `Augmented Context`에서 이전 기록과 검색 자료가 피드백 입력에 들어갔는지 봅니다.
3. `Tool Call Proposals`와 `Tool Results`를 나란히 봅니다. 제안이 있어도 거부될 수 있습니다.
4. `어제 친구와 영화를 봤어요.`처럼 자연스러운 문장도 넣습니다. 수정 후보가 없으면 새 문제와 DB 기록이 만들어지지 않는지 확인합니다.

로컬 검증은 `python -m pytest -q`로 합니다. 실제 모델 평가는 `python evaluate.py --limit 1 --output reports/smoke.json`부터 실행하고, 결과를 사람이 읽어 판단합니다. `reports/`는 실행 후 생성되는 출력 디렉터리이며 저장소의 필수 입력 파일이 아닙니다.

이 앱은 한국어 전체를 판정하는 문법 검사기가 아닙니다. 검색 자료는 선별한 24개 요약이고, 생성 결과는 문맥과 모델에 따라 달라집니다. API가 실패하면 분석도 완료되지 않습니다. 서버의 요청 제한은 단일 프로세스용 간단한 데모 장치입니다. SQLite 파일을 Railway 볼륨에 연결하지 않으면 재배포나 재시작 뒤 기록이 사라질 수 있습니다.

## 자료 출처

`data/grammar.json`은 국립국어원 [한국어기초사전](https://krdict.korean.go.kr/) 항목을 참고해 직접 작성한 기초 문법 요약입니다. 사전 전체나 학습자 말뭉치를 내려받은 파일이 아닙니다. 각 항목의 `source_urls`에 참고 링크가 있습니다. 사전 자료의 이용 조건은 [공식 저작권 정책](https://krdict.korean.go.kr/kor/kboardPolicy/copyRightTermsInfo)을 확인하세요. 별도 표시가 없는 자료에는 저작자표시·동일조건변경허락 2.0 대한민국 조건이 적용됩니다. 멀티미디어 자료는 사용하지 않았습니다. [국립국어원 한국어 학습자 말뭉치](https://kcorpus.korean.go.kr/)도 자료 후보로 검토했지만 이용 신청이 필요해 저장소에 넣지 않았습니다. `data/evaluation_cases.json`의 8문장은 이 프로젝트를 위해 직접 작성했습니다.
