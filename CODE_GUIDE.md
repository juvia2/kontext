# kontext 코드 해설

이 문서는 저장소를 처음 여는 사람이 **입력이 어디로 가고, 모델이 무엇을 돌려주며, 어떤 코드가 그 답을 검사하고 저장하는지** 따라가기 위한 지도입니다. 실행과 배포는 [README.md](README.md)에 있습니다.

`main`은 v2입니다. 벨로그 8~12장이 설명하는 코드는 `v1-blog` 태그에 있습니다(`git checkout v1-blog`).

## 1. 큰 그림

```text
브라우저
   │  POST /api/analyze  (단계가 끝날 때마다 한 줄씩 응답)
app.py ── 요청 확인, 요청 제한, DB 연결
   │
src/pipeline.py  TutorPipeline.run()
   ├ src/learner.py   get_profile()            이전 기록
   ├ src/llm.py       Analyzer.analyze()       모델 호출 1 → build_analysis()로 검사
   ├ src/rag.py       Retriever.search_many()  문법 근거 검색
   ├ src/llm.py       Generator.respond()      모델 호출 2 → repair_output()으로 보정
   └ src/learner.py   ProfileTools.execute()   도구 호출 제안 검증 → 저장
```

Gemini 내부의 토큰화, Attention, Transformer 연산은 API 뒤에 있고 이 저장소에서 볼 수 없습니다. 여기서 구현한 것은 모델 호출을 둘러싼 **시스템**입니다. `src/rag.py`의 벡터는 문서를 찾기 위한 검색 임베딩이며 모델 내부의 토큰 임베딩이 아닙니다.

읽는 순서는 `src/pipeline.py`의 `run()` → `src/schemas.py` → `src/llm.py` → `src/rag.py` → `src/learner.py` → `app.py` → `web/app.js`를 권합니다.

## 2. 한 문장이 이동하는 경로

`어제 책이 읽었어요. 근데 정말 재미있었어요.`를 입력했다고 가정합니다. 모델의 답은 실행마다 달라질 수 있으므로 아래는 흐름을 보여 주는 예입니다.

| 단계 | 코드 | 들어가는 것 → 나오는 것 |
| --- | --- | --- |
| 01 입력 확인 | `TutorPipeline._validate()` | 문장 → 앞뒤 공백을 뗀 문장. 비었거나 500자를 넘으면 실패 |
| 02 학습 기록 읽기 | `LearnerRepository.get_profile()` | 학습자 ID → 수준, 모국어, 최근 30건의 범주별·문법별 횟수 |
| 03 문장 분석 | `Analyzer.analyze()` → `build_analysis()` | 문장, 수준 → `Finding` 목록. `책이→책을`(오류, 0.95), `근데`(괜찮음) 등 |
| 04 문법 근거 검색 | `build_query()` → `Retriever.search_many()` | `조사 \| 책이 → 책을 \| 문장: 어제 책이 읽었어요.` → 문법 자료 `p-object`와 유사도 |
| 05 피드백과 문제 생성 | `_context()` → `Generator.respond()` → `repair_output()` | 원문 + 분석 + 기록 + 근거 → 설명, 문제 1개, `update_learner_profile` 호출 제안 |
| 06 검증 후 저장 | `ProfileTools.execute()` | 제안 → 저장함 / 저장 안 함(이유) |

기억할 경계는 세 가지입니다.

- **모델의 후보 ≠ 피드백 대상.** `build_analysis()`가 원문에 없는 표현, 바꿀 내용이 없는 교정, 겹치는 후보를 버립니다. 판단이 오류·덜 자연스러움이고 확신도가 기준 이상인 것만 `actionable`이 됩니다.
- **검색 결과 ≠ 근거.** 유사도가 `EVIDENCE_MIN_SCORE`보다 낮으면 근거 없이 진행합니다. 모델이 검색되지 않은 자료를 인용하면 `repair_output()`이 그 인용을 지웁니다.
- **도구 호출 제안 ≠ 저장.** 모델은 "이 실수를 이 문법 자료로 기록하자"고 제안만 하고, `ProfileTools`가 검사한 뒤 DB에 씁니다.

## 3. 파일별 구조

### `src/config.py` — 기준은 한 곳에

`Settings`에 모델 이름, DB 경로, 그리고 판단 기준(`feedback_min_confidence`, `record_min_confidence`, `evidence_min_score`, `top_k`)이 있습니다. 다른 파일은 숫자를 직접 쓰지 않고 이 값을 받아 씁니다. 두 번째 모델 호출의 입력에도 `record_min_confidence`를 넣어 지시문과 코드의 기준이 어긋나지 않게 했습니다.

### `src/schemas.py` — JSON의 모양

위쪽은 모델이 반환해야 하는 모양입니다. `AnalysisOutput`(후보 목록과 요약), `TutorOutput`(피드백, 도구 호출 제안, 문제). 아래쪽 `Finding`과 `Analysis`는 코드가 검사한 뒤 쓰는 데이터입니다. 범주는 7개(조사, 어미, 시제, 높임·말투, 문형, 어휘, 맞춤법), 판단은 4개(오류, 덜 자연스러움, 괜찮음, 판단 보류)입니다.

모델에게 원문을 다시 돌려 달라고 하지 않습니다. 원문은 코드가 갖고 있고, 모델은 `expression`과 `occurrence`(몇 번째인지)만 알려 주면 `locate()`가 위치를 찾습니다. **JSON 형식을 지켰다는 것이 판단이 옳다는 뜻은 아닙니다.**

### `src/llm.py` — 모델 호출

`GeminiClient.parse()`는 지시문을 `system_instruction`으로, 입력 데이터를 `input`으로 따로 보내고 `response_format`에 JSON Schema를 넣습니다. `temperature`는 0, `store`는 False입니다. 응답이 Pydantic 검사를 통과하지 못하면 `retries`만큼 다시 요청하고, 끝내 실패하면 `ModelError`를 냅니다.

`ANALYSIS_INSTRUCTIONS`와 `TUTOR_INSTRUCTIONS`가 지시문입니다. 지시문에 적었다고 모델이 지킨다는 보장은 없으므로 같은 규칙을 코드로 한 번 더 검사합니다. `TOOL_SPECS`는 모델에게 보여 주는 도구 정의입니다.

### `data/grammar.json`과 `src/rag.py` — 검색

문법 자료 한 건은 `rule`(규칙), `examples`(올바른 예문), `errors`(틀린 문장 → 고친 문장 → 이유), `contrast`(헷갈리는 표현과의 구분)를 가집니다. `make_chunks()`는 한 건을 `rule` / `errors` / `contrast` 청크로 나눕니다. 학습자의 틀린 문장은 `errors` 청크와 가깝게 나오는 경우가 많습니다.

`Retriever.search_many()`는 모든 청크와 코사인 유사도를 계산하고(같은 범주면 가산점 0.03), 항목별 최고 점수로 순위를 매겨 기준을 넘은 상위 2건을 돌려줍니다. 범주로 미리 거르지 않으므로 모델이 범주를 잘못 붙여도 맞는 자료를 찾을 수 있습니다. 문서 임베딩은 한 번 계산해 `data/.cache/`에 저장합니다. 별도 Vector DB는 없습니다.

검색 질문은 모델의 설명이 아니라 학습자의 표현과 그 문장으로 만듭니다(`build_query()`).

### `src/learner.py` — 모델 밖의 상태

SQLite 테이블은 넷입니다. `learner`(수준, 모국어), `attempt`(쓴 문장), `correction`(기록한 실수와 문법 자료 id), `practice`(문제와 정답, 풀이 결과).

`ProfileTools.execute()`는 제안마다 다섯 가지를 확인합니다. 표현 번호가 있는가, 피드백 대상인가, 확신도가 기록 기준 이상인가, `grammar_id`가 그 표현의 검색 결과에 있는가, 같은 표현을 두 번 제안하지 않았는가. 통과한 것만 한 트랜잭션으로 저장합니다.

연습문제의 정답은 브라우저로 보내지 않습니다. `answer_practice()`가 서버에서 채점하고 첫 번째 답만 기록합니다.

### `src/pipeline.py` — 순서와 기록

`run()`을 위에서 아래로 읽으면 여섯 단계가 그대로 보입니다. `Trace.step()`이 단계마다 이름, 담당(모델/코드), 파일, 성공 여부, 걸린 시간, 결과를 남기고 `on_event`로 바로 알립니다. 화면의 "이 답이 만들어진 과정"이 이 기록입니다. 실패하면 `PipelineFailure`가 그때까지의 기록을 갖고 올라갑니다.

'고친 문장'은 모델이 쓰지 않고 `apply_corrections()`가 '오류' 판단만 제안으로 바꿔 만듭니다.

### `app.py`와 `web/`

`POST /api/analyze`는 파이프라인을 별도 스레드에서 돌리며 사건을 한 줄씩(JSON Lines) 내려보냅니다. `web/app.js`의 `analyze()`가 줄을 읽어 단계 표시를 갱신하고 마지막 줄로 결과를 그립니다. 서버가 보낸 문자열은 모두 `textContent`로만 넣습니다.

그 밖의 경로: `GET/PUT /api/profile`(기록과 설정), `POST /api/practice`(채점), `GET /health`.

### `tests/`와 `evaluate.py`

`tests/fakes.py`의 `FakeModel`은 `GeminiClient` 자리에 들어가 정해 둔 답을 돌려줍니다. 그래서 `Analyzer`, `Generator`, 파이프라인, API의 실제 코드가 API 비용 없이 검사됩니다. `evaluate.py`는 실제 Gemini로 46문장을 실행해 탐지, 오탐, 범주, 검색, 저장을 따로 잽니다.

## 4. 블로그 챕터와 코드

| 장 | 주제 | v1 (`v1-blog` 태그) | v2 (`main`)에서 달라진 점 |
| --- | --- | --- | --- |
| 01 | 벡터와 유사도 | `src/rag.py`의 `cosine()` | 같음 |
| 02 | 임베딩 | `GeminiEmbedder` | 50개씩 나눠 호출, 결과를 파일로 저장 |
| 05 | RAG | `data/grammar.json`, `src/rag.py` | 자료 스키마와 청킹을 새로 설계, 기준 점수 도입 |
| 06 | Tool Calling | `ProfileTools` | 제안에 `grammar_id`와 이유가 실림, 검증 항목 추가 |
| 07 | 전체 설계 | `src/pipeline.py` | 7장의 평가 기준을 `evaluate.py` 지표로 구현 |
| 08 | 폴더 구조 | 전체 | `config.py`, `schemas.py` 분리 |
| 09 | `src/llm.py` | `GeminiClient`, `Analyzer` | 지시문 분리 전달, 재시도, 실패 대신 버리기 |
| 10 | `data/`, `src/rag.py` | (미발행) | — |
| 11 | `src/pipeline.py` | `run()`, `_context()` | 단계 6개로 정리, 실시간 기록 |
| 12 | `src/learner.py` | (미발행) | — |

## 5. 알아 둘 한계

- 도구 호출은 Gemini의 네이티브 function calling이 아니라 구조화 출력의 `tool_calls` 필드로 받습니다. 저장 결과가 답변 생성에 필요하지 않아 모델 호출을 한 번 줄이는 쪽을 택했습니다(7장 7.14의 "결과를 다시 Context에 전달"과 다른 점). 이유는 [docs/DECISIONS.md](docs/DECISIONS.md)에 있습니다.
- `EVIDENCE_MIN_SCORE`는 실제 임베딩 점수로 보정하지 않은 초기값입니다.
- 문법 자료는 검수 전입니다.
- 인증이 없습니다. 학습자 ID를 아는 사람은 그 기록을 볼 수 있습니다.
