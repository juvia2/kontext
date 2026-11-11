# 작업 핸드오프

- 마지막 정리: Claude, 2026-11-11 (이전: Codex, 2026-10-23)
- 단계: v2 로컬 커밋 완료·푸시 전, 실제 모델 검증 전, 블로그 10·12장 미발행

## 현재 상태

- v2는 `master`에 로컬 커밋되어 있고 **아직 푸시하지 않았다**(Claude 작업 환경에 GitHub 인증이 없어 푸시 실패). v1은 로컬 태그 `v1-blog`(커밋 `49b8a22`)에 있고 태그도 푸시 전이다. 배포는 푸시 후 Railway에서 확인한다.
- v2 변경: `src/config.py`·`src/schemas.py` 신설, `src/llm.py`·`src/rag.py`·`src/learner.py`·`src/pipeline.py`·`app.py`·`evaluate.py`·`web/` 전부 재작성, `data/grammar.json` 59건과 `data/evaluation_cases.json` 46문장 새로 작성, `tests/` 재작성(`tests/test_mobile.py` 삭제), `requirements-dev.txt` 분리.
- 결정과 이유는 `docs/DECISIONS.md`, 점검 내용은 `docs/AUDIT-2026-11-11.md`, UI 시안은 Claude 아티팩트 "Kontext UI 수정 시안".

## 검증

- `python -m pytest -q`: 27건 통과(가짜 모델·가짜 임베딩).
- 가짜 모델로 서버를 띄워 390px·1440px 화면에서 분석 성공, 실패, 고칠 곳 없는 문장, 연습문제 채점, 학습 기록, 설정 저장을 확인했다. 가로 넘침과 콘솔 오류 없음.
- **하지 않은 것: 실제 Gemini 호출.** 작업 환경에서 Gemini API에 접속할 수 없었다. 지시문 품질, `system_instruction`·`generation_config`·`store` 인자의 실제 동작, 임베딩 점수 분포는 확인되지 않았다(SDK 2.28.0의 요청 타입에 해당 필드가 있는 것만 확인).

## 미완료·다음 작업

1. 로컬에서 실제 모델 확인: `pip install -r requirements-dev.txt` → `python evaluate.py --limit 3` → `python evaluate.py`. 오류가 나면 `reports/evaluation.json`의 trace부터 본다.
2. 평가 결과의 `lowest_top_score_among_hits`를 보고 `EVIDENCE_MIN_SCORE`(현재 0.5, 미보정)를 정한다. 기준을 정할 때는 `python evaluate.py --min-score 0`으로 점수 분포를 먼저 본다.
3. README의 "테스트와 평가" 절에 결과 표를 넣는다.
4. `data/grammar.json` 59건을 한국어기초사전과 대조해 검수한다.
5. `git push origin master`와 `git push origin v1-blog`로 올린다. (`.DS_Store`는 스테이징에서 뺐고 `.gitignore`에 넣었다.)
6. 블로그: 10장(`data/`, `rag.py`)과 12장(`learner.py`)을 v1 기준으로 발행해 코드 읽기 파트를 닫고, 8~12장의 코드 링크를 `v1-blog` 태그로 바꾼다. 시리즈 README에 Kontext·GitHub·3부 안내를 추가한다. v2는 3부 "데모를 프로덕트로"로 연재한다(안: 13 뜯어보니 고장 난 곳, 14 문법 자료와 검색 재설계, 15 도구 호출의 경계, 16 평가로 증명하기, 17 UI와 배포).
7. Railway 공개 주소와 배포 상태 확인(기존 미해결 항목). `DATABASE_PATH`를 쓰고 있다면 새 테이블이 같은 파일에 생긴다.
8. LICENSE 파일 추가 여부 결정.

## 이어받을 때

`git status`와 이 문서, `docs/DECISIONS.md`부터 확인한다. `.env`는 핸드오프에 복사하지 않는다. 작업 종료 시 이 문서를 갱신한다.
