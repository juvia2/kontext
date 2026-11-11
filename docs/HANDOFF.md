# 작업 핸드오프

- 마지막 정리: Claude 채팅, 2026-11-11 17:25 KST (이전: Codex, 2026-10-23)
- 다음 작업자: **Claude Code** (Mac에서 실행 — GitHub 인증, Gemini 접속, Railway CLI를 쓸 수 있다)
- 단계: v2 로컬 커밋 완료, **푸시·배포·실제 모델 검증 전**

## Claude Code가 바로 할 일 (순서대로)

사용자 지시는 "커밋하고 변경된 UI로 배포"다. 커밋까지 됐고 나머지가 남았다. 사용자는 설명보다 끝까지 실행한 결과를 원한다.

1. **상태 확인**: `git status`(깨끗해야 함), `git log --oneline -3`(맨 위가 v2 커밋), `git tag -l`(`v1-blog` 있음).
2. **실제 모델로 먼저 확인** — 이 코드는 Gemini로 한 번도 실행되지 않았다.
   ```bash
   source .venv/bin/activate && pip install -r requirements-dev.txt
   python -m pytest -q                 # 27건 통과해야 함
   python evaluate.py --limit 3        # 실제 호출. 실패하면 reports/evaluation.json의 trace 확인
   ```
   실패할 수 있는 지점: `src/llm.py`의 `GeminiClient.parse()`가 보내는 `system_instruction`, `generation_config={"temperature": 0}`, `store=False`, `response_format`(SDK 2.28.0 타입에 필드가 있는 것만 확인함), Pydantic 스키마의 `$defs`/enum을 Gemini가 받는지, `src/rag.py`의 임베딩 50개 묶음 호출.
3. **전체 평가와 기준 보정**: `python evaluate.py --min-score 0`으로 점수 분포를 보고 `EVIDENCE_MIN_SCORE`(현재 0.5, 임시값)를 정한 뒤 `python evaluate.py`. 결과 표를 README "테스트와 평가" 절에 넣는다("아직 평가하지 않았습니다" 문장 교체).
4. **푸시**: `git push origin master && git push origin v1-blog`.
5. **배포**: `railway status`로 연결 확인. 저장소가 연결돼 있으면 푸시로 자동 배포, 아니면 `railway up`. `railway domain`으로 공개 주소 확인. Variables에 `GEMINI_API_KEY` 필요. 과거에 공개 주소를 확인하지 못했으므로 프로젝트가 없으면 새로 만든다(README "Railway에 배포" 절).
6. **배포 확인**: 공개 주소에서 예시 문장 분석, 연습문제 풀이, 학습 기록 탭, 모바일 폭을 확인한다. `/health`는 키가 없어도 200이므로 화면에서 직접 분석해 봐야 한다.
7. 끝나면 이 문서와 README(공개 주소)를 갱신하고 커밋한다.

## 이번 채팅에서 한 일과 사용자가 말한 것

- 요청 흐름: 프로그램 점검 → UI 시안 → "색감·구성이 촌스럽다, 로고 색 바꿔도 된다" → 새 시안 승인("좋아") → "기준이 부실했던 것 바로잡았나" → "처음 기획 확인하고 다시 만들다시피 제대로 만들어" → "커밋하고 배포" → "핸드오프로 넘겨, Claude Code에서 작업".
- 프로젝트 목적: 원래 벨로그 「LLM.zip | 압축 해제」에서 코드를 뜯어보는 샘플. 지금은 포트폴리오용으로 디벨롭 중이며 블로그 글과 흐름을 맞춰야 한다.
- 점검: `docs/AUDIT-2026-11-11.md` (P0 5건, 설계, UI, 블로그 불일치).
- UI 시안: Claude 아티팩트 "Kontext UI 수정 시안" https://claude.ai/artifact/KpXp57zRdiPw138P2q6x2S (흰 바탕·검정·코발트 `#2b44e7`, 워드마크 `kontext`, 모바일 3장 + 데스크톱 1장). `web/`이 이 시안의 구현이다.
- 재작성 내용과 이유: `docs/DECISIONS.md`의 2026-11-11 항목.
- v1 보존: 로컬 태그 `v1-blog` = 커밋 `49b8a22`. 블로그 8·9·11장이 이 코드를 인용한다.

## 검증된 것과 안 된 것

- 검증: pytest 27건(가짜 모델·가짜 임베딩). 가짜 모델로 서버를 띄워 390px·1440px에서 분석 성공, 실패 화면, 고칠 곳 없는 문장, 연습문제 채점, 학습 기록, 설정 저장 확인. 가로 넘침·콘솔 오류 없음.
- 미검증: 실제 Gemini 호출 전부(지시문 품질, 요청 인자, 임베딩 점수), Railway 배포, 실제 휴대폰.
- 채팅 환경에서 막힌 것: Gemini API 접속 불가, `git push` 인증 없음, 저장소 접근 권한 추가 거부됨.

## 그다음 작업

- `data/grammar.json` 59건 검수(Claude가 새로 쓴 것, 전문가 검수 전). 사전 링크는 검색 결과 주소다.
- 블로그: 10장(`data/`, `rag.py`)과 12장(`learner.py`)을 v1 기준으로 발행, 8~12장 코드 링크를 `v1-blog` 태그로 교체, 시리즈 README에 Kontext·GitHub·3부 안내 추가. v2는 3부 "데모를 프로덕트로"(안: 13 뜯어보니 고장 난 곳, 14 문법 자료와 검색 재설계, 15 도구 호출의 경계, 16 평가로 증명하기, 17 UI와 배포). Codex 채팅의 10장 초안은 저장소에 없다.
- 시안에는 있고 구현에 없는 것: 모바일 전용 분석 과정 화면(지금은 결과 아래에 펼쳐짐), "오늘 n문장째" 표시.
- 결정 대기: 네이티브 function calling으로 바꿀지(현재는 구조화 출력의 `tool_calls`), LICENSE 추가.

## 이어받을 때

`git status`, 이 문서, `docs/DECISIONS.md` 순으로 본다. `.env`와 키는 문서에 복사하지 않는다. 작업을 마치면 이 문서를 갱신한다.
