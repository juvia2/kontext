"""모델 밖에 남는 학습자 상태(SQLite)와, 모델의 도구 호출 제안을 검사해 실행하는 코드."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from src.config import Settings
from src.particles import particle_conflict
from src.rag import Match
from src.schemas import Analysis, PracticeQuestion, ProfileUpdateCall

LEVELS = ("A1", "A2", "B1", "B2")


@dataclass(frozen=True)
class LearnerProfile:
    learner_id: str
    level: str
    native_language: str
    category_counts: dict[str, int]   # 최근 기록의 범주별 횟수
    grammar_counts: dict[str, int]    # 최근 기록의 문법 자료별 횟수

    def as_context(self) -> dict:
        return asdict(self)


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS learner (
            learner_id TEXT PRIMARY KEY,
            level TEXT NOT NULL,
            native_language TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS attempt (
            request_id TEXT PRIMARY KEY,
            learner_id TEXT NOT NULL,
            utterance TEXT NOT NULL,
            corrected TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS correction (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            learner_id TEXT NOT NULL,
            finding_index INTEGER NOT NULL,
            expression TEXT NOT NULL,
            suggestion TEXT NOT NULL,
            category TEXT NOT NULL,
            judgment TEXT NOT NULL,
            grammar_id TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(request_id, finding_index)
        );
        CREATE TABLE IF NOT EXISTS practice (
            request_id TEXT PRIMARY KEY,
            learner_id TEXT NOT NULL,
            grammar_id TEXT NOT NULL,
            prompt TEXT NOT NULL,
            choices TEXT NOT NULL,
            answer_index INTEGER NOT NULL,
            explanation TEXT NOT NULL,
            chosen_index INTEGER,
            correct INTEGER,
            answered_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_correction_learner ON correction(learner_id, id);
        CREATE INDEX IF NOT EXISTS idx_attempt_learner ON attempt(learner_id);
        """
    )
    return connection


class LearnerRepository:
    RECENT = 30  # 개인화에 쓰는 최근 기록 수

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def ensure_learner(self, learner_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO learner(learner_id, level, native_language) VALUES (?, 'B1', '')",
                (learner_id,))

    def set_profile(self, learner_id: str, level: str, native_language: str) -> None:
        if level not in LEVELS:
            raise ValueError("알 수 없는 수준입니다")
        with self.connection:
            self.connection.execute(
                "UPDATE learner SET level = ?, native_language = ? WHERE learner_id = ?",
                (level, native_language, learner_id))

    def _recent_counts(self, learner_id: str, column: str) -> dict[str, int]:
        rows = self.connection.execute(
            f"SELECT {column} AS key, COUNT(*) AS n FROM "
            "(SELECT * FROM correction WHERE learner_id = ? ORDER BY id DESC LIMIT ?) "
            "GROUP BY key ORDER BY n DESC, key", (learner_id, self.RECENT)).fetchall()
        return {row["key"]: row["n"] for row in rows}

    def get_profile(self, learner_id: str) -> LearnerProfile:
        row = self.connection.execute(
            "SELECT level, native_language FROM learner WHERE learner_id = ?", (learner_id,)).fetchone()
        if row is None:
            raise LookupError(f"학습자를 찾을 수 없습니다: {learner_id}")
        return LearnerProfile(learner_id, row["level"], row["native_language"],
                              self._recent_counts(learner_id, "category"),
                              self._recent_counts(learner_id, "grammar_id"))

    def save_attempt(self, request_id: str, learner_id: str, utterance: str, corrected: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO attempt(request_id, learner_id, utterance, corrected) VALUES (?, ?, ?, ?)",
                (request_id, learner_id, utterance, corrected))

    def record_corrections(self, rows: list[tuple]) -> list[bool]:
        """여러 건을 한 트랜잭션으로 저장한다. 같은 요청의 같은 표현은 한 번만 들어간다."""
        inserted: list[bool] = []
        with self.connection:
            for row in rows:
                cursor = self.connection.execute(
                    "INSERT OR IGNORE INTO correction(request_id, learner_id, finding_index, expression, "
                    "suggestion, category, judgment, grammar_id, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row)
                inserted.append(cursor.rowcount == 1)
        return inserted

    def save_practice(self, request_id: str, learner_id: str, question: PracticeQuestion) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO practice(request_id, learner_id, grammar_id, prompt, choices, "
                "answer_index, explanation) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (request_id, learner_id, question.grammar_id, question.prompt,
                 json.dumps(question.choices, ensure_ascii=False), question.answer_index, question.explanation))

    def answer_practice(self, learner_id: str, request_id: str, choice_index: int) -> dict | None:
        """정답은 서버에만 있다. 첫 번째 답만 기록하고 결과와 해설을 돌려준다."""
        row = self.connection.execute(
            "SELECT * FROM practice WHERE request_id = ? AND learner_id = ?", (request_id, learner_id)).fetchone()
        if row is None or not 0 <= choice_index < len(json.loads(row["choices"])):
            return None
        if row["chosen_index"] is None:
            with self.connection:
                self.connection.execute(
                    "UPDATE practice SET chosen_index = ?, correct = ?, answered_at = CURRENT_TIMESTAMP "
                    "WHERE request_id = ?", (choice_index, int(choice_index == row["answer_index"]), request_id))
        return {"correct": choice_index == row["answer_index"], "answer_index": row["answer_index"],
                "explanation": row["explanation"]}

    def stats(self, learner_id: str) -> dict:
        one = lambda sql: self.connection.execute(sql, (learner_id,)).fetchone()[0] or 0
        return {
            "sentences": one("SELECT COUNT(*) FROM attempt WHERE learner_id = ?"),
            "corrections": one("SELECT COUNT(*) FROM correction WHERE learner_id = ?"),
            "practice_total": one("SELECT COUNT(*) FROM practice WHERE learner_id = ? AND chosen_index IS NOT NULL"),
            "practice_correct": one("SELECT SUM(correct) FROM practice WHERE learner_id = ?"),
        }

    def history(self, learner_id: str, limit: int = 10) -> list[dict]:
        rows = self.connection.execute(
            "SELECT c.expression, c.suggestion, c.category, c.judgment, c.grammar_id, c.created_at, "
            "a.utterance, p.correct AS practice_correct "
            "FROM correction c LEFT JOIN attempt a ON a.request_id = c.request_id "
            "LEFT JOIN practice p ON p.request_id = c.request_id "
            "WHERE c.learner_id = ? ORDER BY c.id DESC LIMIT ?", (learner_id, limit)).fetchall()
        return [dict(row) for row in rows]


@dataclass(frozen=True)
class ToolResult:
    name: str
    arguments: dict
    status: str   # saved | duplicate | rejected
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


class ProfileTools:
    """update_learner_profile 도구의 실행부.

    모델은 '이 실수를 기록하자'고 제안만 한다. 이 클래스가 제안을 검사하고, 통과한 것만 DB에 쓴다.
    """
    NAME = "update_learner_profile"

    def __init__(self, repository: LearnerRepository, settings: Settings):
        self.repository = repository
        self.settings = settings

    def _rejection(self, call: ProfileUpdateCall, analysis: Analysis,
                   evidence: dict[int, list[Match]], seen: set[int]) -> str | None:
        if call.index >= len(analysis.findings):
            return "없는 표현 번호"
        finding = analysis.findings[call.index]
        if not finding.actionable:
            return "피드백 대상이 아닌 표현"
        if finding.confidence < self.settings.record_min_confidence:
            return "확신도가 기록 기준보다 낮음"
        if call.grammar_id not in {match.entry.id for match in evidence.get(call.index, [])}:
            return "검색된 근거에 없는 문법 자료"
        if particle_conflict(finding.expression, finding.suggestion, call.grammar_id):
            return "교정한 조사와 맞지 않는 문법 자료"
        if call.index in seen:
            return "같은 표현을 두 번 제안함"
        return None

    def execute(self, *, learner_id: str, request_id: str, calls: list[ProfileUpdateCall],
                analysis: Analysis, evidence: dict[int, list[Match]]) -> list[ToolResult]:
        results: list[ToolResult | None] = [None] * len(calls)
        accepted: list[int] = []
        rows: list[tuple] = []
        seen: set[int] = set()
        for position, call in enumerate(calls):
            reason = self._rejection(call, analysis, evidence, seen)
            if reason is not None:
                results[position] = ToolResult(self.NAME, call.model_dump(), "rejected", reason)
                continue
            seen.add(call.index)
            finding = analysis.findings[call.index]
            accepted.append(position)
            rows.append((request_id, learner_id, finding.index, finding.expression, finding.suggestion,
                         finding.category.value, finding.judgment.value, call.grammar_id, finding.confidence))
        for position, inserted in zip(accepted, self.repository.record_corrections(rows)):
            results[position] = ToolResult(
                self.NAME, calls[position].model_dump(),
                "saved" if inserted else "duplicate",
                "학습 기록에 저장함" if inserted else "이미 저장된 기록")
        return [result for result in results if result is not None]
