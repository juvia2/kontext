# kontext — 답이 만들어진 과정까지 보여 주는 한국어 학습 LLM 데모

한국어 문장을 쓰면 고칠 곳을 찾아 문법 근거와 함께 설명하고, 연습문제를 내고, 실수를 학습 기록에 남깁니다. 그리고 **그 답이 어떤 단계를 거쳐 만들어졌는지** — 모델이 한 일과 코드가 한 일 — 를 화면 오른쪽에 그대로 보여 줍니다.

벨로그 시리즈 [「LLM.zip | 압축 해제」](https://velog.io/@olivia02/series/LLM.zip-압축-해제)의 실습 저장소입니다. 7장에서 설계한 AI Language Tutor를 실제로 구현했습니다.

> **버전 안내** 시리즈 8~12장(코드 읽기)은 `v1-blog` 태그의 코드를 설명합니다. `main`은 그 코드를 점검해 다시 만든 v2입니다. 무엇을 왜 바꿨는지는 [docs/DECISIONS.md](docs/DECISIONS.md)와 [docs/AUDIT-2026-11-11.md](docs/AUDIT-2026-11-11.md)에 있습니다.

**공개 데모:** https://web-production-73f530f5.up.railway.app (Railway Free 플랜, 학습 기록은 재배포 때 초기화됩니다)

코드 해설은 [CODE_GUIDE.md](CODE_GUIDE.md)에 있습니다.

## 한 문장이 거치는 여섯 단계

```text
문장 입력
  │
  ├ 01 입력 확인            코드   src/pipeline.py
  ├ 02 학습 기록 읽기        코드   src/learner.py   이전에 틀린 문법과 횟수
  ├ 03 문장 분석            모델   src/llm.py       살펴볼 표현, 판단(오류/덜 자연스러움/괜찮음/보류), 확신도
  │      └ 코드가 후보를 검사: 원문에 없는 표현, 바꿀 내용이 없는 교정, 겹치는 후보는 버림
  ├ 04 문법 근거 검색        코드   src/rag.py       표현마다 문법 자료 70건에서 검색, 기준 점수 미만이면 근거 없음
  ├ 05 피드백과 문제 생성     모델   src/llm.py       원문 + 분석 + 기록 + 근거 → 설명, 객관식 1문제, 도구 호출 제안
  └ 06 검증 후 저장          코드   src/learner.py   제안을 검사해 통과한 것만 SQLite에 기록
  │
화면: 밑줄 친 원문 · 교정 카드 · 문법 근거 · 연습문제 · 분석 과정
```

고칠 표현이 없으면 04·05를 건너뛰고 모델을 한 번만 호출합니다. 순서가 코드에 정해져 있으므로 자율 Agent가 아닌 Workflow입니다.

## 이 저장소에서 확인할 수 있는 것

| 주제 | 볼 곳 |
| --- | --- |
| 모델에게 무엇을 요청하고 답을 어떻게 검사하나 | `src/schemas.py`, `src/llm.py` |
| 판단 기준 숫자는 어디서 정하나 | `src/config.py` 한 곳 |
| 문서를 어떻게 나누고 찾나 (RAG) | `data/grammar.json`, `src/rag.py` |
| 검색 결과가 어떻게 모델 입력이 되나 | `src/pipeline.py`의 `_context()` |
| 모델의 도구 호출 제안과 실제 실행의 경계 | `src/learner.py`의 `ProfileTools` |
| 모델이 형식을 어겼을 때 | `GeminiClient.parse()`의 재시도, `build_analysis()`와 `repair_output()` |
| 품질을 어떻게 재나 | `evaluate.py`, `data/evaluation_cases.json` |

## 판단 기준

모든 숫자는 `src/config.py`에 있고 환경 변수로 바꿀 수 있습니다.

| 기준 | 기본값 | 뜻 |
| --- | --- | --- |
| `FEEDBACK_MIN_CONFIDENCE` | 0.6 | 모델이 매긴 확신도가 이 값 이상인 오류·덜 자연스러운 표현만 피드백한다 |
| `RECORD_MIN_CONFIDENCE` | 0.75 | 학습 기록에 남기는 최소 확신도 |
| `EVIDENCE_MIN_SCORE` | 0.74 | 검색 유사도가 이보다 낮으면 근거로 쓰지 않는다 |
| `EVIDENCE_TOP_K` | 2 | 표현 하나에 붙이는 근거의 최대 개수 |

확신도는 모델의 자기 추정치이고 유사도는 검색 순위용 숫자입니다. 둘 다 정답 확률이 아닙니다. `EVIDENCE_MIN_SCORE` 0.74는 실제 평가 53문장의 점수로 정했습니다. 맞는 근거의 최고 점수는 모두 0.745 이상이었고, 무관한 근거 중 이보다 낮은 것은 0.73대였습니다. 자료를 바꾸면 `python evaluate.py --min-score 0`으로 다시 확인하세요.

## 폴더 구조

```text
app.py                  FastAPI: 화면, API, 요청 제한
src/config.py           설정과 판단 기준
src/schemas.py          모델과 주고받는 데이터의 모양
src/llm.py              Gemini 호출, 지시문, 분석 후보 검사
src/rag.py              문법 자료 청킹, 임베딩, 검색
src/learner.py          SQLite 학습 기록, 도구 호출 검증과 실행
src/pipeline.py         여섯 단계의 순서와 실행 기록
data/grammar.json       문법 자료 70건 (규칙, 예문, 오류 사례 191쌍, 구분 기준)
data/evaluation_cases.json  평가 문장 53개
web/                    화면 (HTML, CSS, JS — 빌드 도구 없음)
tests/                  가짜 모델로 흐름을 검사하는 테스트
evaluate.py             실제 Gemini로 평가 지표를 내는 도구
```

LangChain, Vector DB, 프런트엔드 프레임워크를 쓰지 않았습니다. 자료가 179개 청크뿐이라 메모리에서 코사인 유사도를 직접 계산하는 편이 코드를 읽기 쉽습니다.

## 로컬에서 실행

Python 3.12 기준입니다.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # GEMINI_API_KEY에 본인 키 입력
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000`을 엽니다. [Google AI Studio](https://aistudio.google.com/apikey)에서 키를 만들 수 있습니다. 키를 채팅이나 GitHub에 올리지 마세요. 문법 자료 임베딩은 `data/.cache/`에 계산해 둔 파일을 함께 커밋해 두었습니다. `grammar.json`을 고치면 첫 분석 때 다시 계산합니다(청크가 179개라 무료 등급의 분당 100건 한도에 걸리면 1분가량 기다렸다 이어 갑니다).

## 테스트와 평가

```bash
python -m pytest -q                     # 가짜 모델·가짜 임베딩, API 호출 없음
python evaluate.py --limit 3            # 실제 Gemini 호출: 먼저 3문장만
python evaluate.py                      # 53문장 전체 → reports/evaluation.json
```

평가는 7장에서 정한 기준을 단계별로 잽니다.

| 지표 | 뜻 |
| --- | --- |
| `detection_recall` / `detection_precision` | 고쳐야 할 표현을 찾았는가 / 찾은 것 중 맞는 비율 |
| `clean_sentence_false_alarm_rate` | 고칠 곳이 없는 문장 10개에서 무언가를 고치라고 한 비율 |
| `category_accuracy` | 찾은 표현의 범주가 기대와 같은가 |
| `retrieval_hit_rate` | 기대한 문법 자료가 근거에 들어왔는가 |
| `recorded_rate` | 찾은 실수가 학습 기록에 저장됐는가 |

**실제 모델 평가 결과** (2026-11-12, `gemini-3.5-flash-lite` + `gemini-embedding-2`, `EVIDENCE_MIN_SCORE` 0.74, 53문장)

| 지표 | 결과 |
| --- | --- |
| 실행 실패 | 1건 (`p09`, 모델 응답 형식 오류 2회) |
| 탐지 재현율 | 0.884 (43개 중 38개) |
| 탐지 정밀도 | 0.974 (기대하지 않은 교정 1건) |
| 고칠 곳 없는 문장 오탐률 | 0.1 (10문장 중 1문장) |
| 범주 정확도 | 0.868 |
| 검색 적중률 | 1.0 (맞는 근거 최고 점수 최저 0.745) |
| 기록 저장률 | 0.974 |
| 평균 처리 시간 | 약 11.6초 |

놓친 표현은 `커피를 좋아요`의 조사, `비가 와서 ~하세요`(-아서 + 명령), `공부하러 책을 샀어요`(-러 + 이동 동사 아님), `친구는 ~고 싶어요`(3인칭 -고 싶다), `별로 재미있어요`입니다. 오탐 1건은 구어 `근데`를 고칠 곳으로 잡은 것입니다. 범주가 어긋난 5건은 모두 맞게 고쳤지만 범주만 다르게 붙였습니다(예: `학생이예요`를 맞춤법이 아닌 어미로). 같은 문장도 실행마다 모델 답이 달라집니다. 보정 실행(`--min-score 0`)에서는 `영화이 봤어요`를 `영화가`로 잘못 고쳤고, 이 실행에서는 `영화를`로 고쳤습니다. 숫자는 보조 지표이고, 설명이 타당한지는 `reports/evaluation.json`을 사람이 읽고 판단해야 합니다(평가 결과 파일은 커밋하지 않습니다).

## Railway에 배포

FastAPI 서버 하나가 화면과 API를 함께 제공합니다. `Procfile`이 `uvicorn app:app --host 0.0.0.0 --port $PORT`를 실행합니다.

1. GitHub 저장소를 Railway에 연결합니다(New Project → Deploy from GitHub repo).
2. Variables에 `GEMINI_API_KEY`를 넣습니다. 키는 저장소가 아니라 Railway에만 둡니다.
3. 기록을 재배포 뒤에도 유지하려면 Volume을 `/data`에 마운트하고 `DATABASE_PATH=/data/kontext.sqlite3`를 설정합니다. `/app/data`에는 마운트하지 마세요. 그 경로에 `grammar.json`이 있습니다.
4. Healthcheck 경로는 `/health`입니다. 서버가 떠 있는지만 확인하므로 Gemini 연결은 화면에서 문장 하나로 따로 확인합니다.
5. Settings → Networking → Generate Domain으로 공개 주소를 만듭니다.

Railway 체험 플랜의 외부 네트워크 제한은 Gemini 호출을 막을 수 있습니다. [플랜 안내](https://docs.railway.com/pricing/plans)를 확인하세요.

현재 공개 데모는 GitHub 푸시로 자동 배포되지 않아 `railway up --service web`으로 올립니다. `.python-version`은 `3.12`로 둡니다. `3.12.0`처럼 정확한 패치 버전을 적으면 Railway 빌더가 설치에 실패했습니다.

## 데이터와 한계

- `data/grammar.json`의 70건은 한국어 교육에서 다루는 초·중급 문법을 이 프로젝트를 위해 새로 쓴 요약입니다. 사전의 문장을 옮기지 않았습니다. 각 항목의 링크는 [한국어기초사전](https://krdict.korean.go.kr/) **검색 결과**로 연결되며 확인용입니다. **전문가 검수를 거치지 않았으므로** 사전과 대조해 고칠 곳이 있으면 고쳐 주세요.
- 문법 자료에 없는 범위의 실수는 근거 없이 설명되고 학습 기록에 남지 않습니다.
- `-었어서`처럼 규범과 실제 쓰임이 다른 표현은 '오류'가 아니라 '덜 자연스러움'으로 다룹니다.
- 학습자 ID는 브라우저에 저장되는 임의 값이고 로그인이 아닙니다. 입력한 문장은 서버의 SQLite에 저장되고 Gemini API로 전송됩니다. 이름 같은 민감한 정보를 넣지 마세요.
- 요청 제한(학습자당 시간당 20회)은 서버 프로세스 하나의 메모리에서만 동작합니다.
- 모델 응답은 실행할 때마다 달라질 수 있습니다. 이 앱은 한국어 전체를 판정하는 문법 검사기가 아닙니다.
