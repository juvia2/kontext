from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from src.rag import SearchMatch
from src.llm import Judgment, LanguageAnalysis, ProfileUpdateProposal

# Chapter 06: learner state stored outside the LLM.

@dataclass(frozen=True)
class LearnerProfile:
    learner_id: str
    level: str
    native_language: str
    recent_patterns: dict[str, int]

    def as_context(self) -> dict:
        return asdict(self)


# SQLite keeps the small demo self-contained.

def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS learners (
            learner_id TEXT PRIMARY KEY,
            level TEXT NOT NULL,
            native_language TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS error_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            learner_id TEXT NOT NULL REFERENCES learners(learner_id),
            request_id TEXT NOT NULL,
            error_index INTEGER NOT NULL,
            expression TEXT NOT NULL,
            error_type TEXT NOT NULL,
            suggestion TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(learner_id, request_id, error_index)
        );
        CREATE INDEX IF NOT EXISTS idx_history_learner ON error_history(learner_id, created_at);
        """
    )
    return connection


class LearnerRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def ensure_learner(self, learner_id: str, level: str = "B1", native_language: str = "English") -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO learners(learner_id, level, native_language) VALUES (?, ?, ?)",
                (learner_id, level, native_language),
            )

    def get_profile(self, learner_id: str) -> LearnerProfile:
        learner = self.connection.execute(
            "SELECT learner_id, level, native_language FROM learners WHERE learner_id = ?", (learner_id,)
        ).fetchone()
        if learner is None:
            raise LookupError(f"Learner not found: {learner_id}")
        counts = self.connection.execute(
            "SELECT error_type, COUNT(*) AS n FROM error_history WHERE id IN "
            "(SELECT id FROM error_history WHERE learner_id = ? ORDER BY id DESC LIMIT 20) "
            "GROUP BY error_type ORDER BY n DESC", (learner_id,)
        ).fetchall()
        return LearnerProfile(
            learner_id=learner["learner_id"], level=learner["level"],
            native_language=learner["native_language"],
            recent_patterns={row["error_type"]: row["n"] for row in counts},
        )

    def recent_history(self, learner_id: str, limit: int = 5) -> list[dict]:
        rows = self.connection.execute(
            "SELECT expression, error_type, suggestion, confidence, created_at FROM error_history "
            "WHERE learner_id = ? ORDER BY id DESC LIMIT ?", (learner_id, limit)
        ).fetchall()
        return [dict(row) for row in rows]

    def record_error(self, learner_id: str, request_id: str, error_index: int,
                     expression: str, error_type: str, suggestion: str, confidence: float) -> bool:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO error_history"
                "(learner_id, request_id, error_index, expression, error_type, suggestion, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (learner_id, request_id, error_index, expression, error_type, suggestion, confidence),
            )
        return cursor.rowcount == 1

    def record_errors_batch(self, records: list[tuple[str, str, int, str, str, str, float]]) -> list[bool]:
        inserted: list[bool] = []
        with self.connection:
            for record in records:
                cursor = self.connection.execute(
                    "INSERT OR IGNORE INTO error_history"
                    "(learner_id, request_id, error_index, expression, error_type, suggestion, confidence) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", record,
                )
                inserted.append(cursor.rowcount == 1)
        return inserted

    def seed_demo_history(self, learner_id: str) -> None:
        seeds = [
            (0, "연결 표현", "connective_ending", "문맥에 맞는 연결어미"),
            (1, "이유 연결", "connective_ending", "-아서/-어서"),
            (2, "절 연결", "connective_ending", "-는데"),
            (3, "주제 조사", "particle_selection", "은/는"),
            (4, "목적격 조사", "particle_selection", "을/를"),
        ]
        for index, expression, category, suggestion in seeds:
            self.record_error(learner_id, "demo-seed", index, expression, category, suggestion, 1.0)


@dataclass(frozen=True)
class ToolResult:
    name: str
    arguments: dict
    status: str
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


# A model proposes a write; this class checks it before changing the database.

class ProfileTools:
    def __init__(self, repository: LearnerRepository):
        self.repository = repository

    @staticmethod
    def _rejection(learner_id: str, proposal: ProfileUpdateProposal,
                   analysis: LanguageAnalysis, evidence: list[SearchMatch]) -> ToolResult | None:
        arguments = {"learner_id": learner_id, **proposal.model_dump()}
        if proposal.error_index >= len(analysis.errors):
            return ToolResult("update_learner_profile", arguments, "rejected", "invalid error_index")
        error = analysis.errors[proposal.error_index]
        if (proposal.error_type != error.category.value or
                proposal.expression != error.expression or proposal.suggestion != error.suggestion):
            return ToolResult("update_learner_profile", arguments, "rejected", "proposal differs from analysis")
        if error.judgment not in (Judgment.ERROR, Judgment.LESS_NATURAL) or error.confidence < 0.75:
            return ToolResult("update_learner_profile", arguments, "rejected", "judgment or confidence threshold")
        if not evidence:
            return ToolResult("update_learner_profile", arguments, "rejected", "no retrieved evidence")
        return None

    @staticmethod
    def _stored_result(learner_id: str, proposal: ProfileUpdateProposal, inserted: bool) -> ToolResult:
        return ToolResult(
            "update_learner_profile", {"learner_id": learner_id, **proposal.model_dump()},
            "updated" if inserted else "already_recorded",
            "stored in error_history" if inserted else "idempotent replay",
        )

    def update(self, *, learner_id: str, request_id: str, proposal: ProfileUpdateProposal,
               analysis: LanguageAnalysis, evidence: list[SearchMatch]) -> ToolResult:
        rejection = self._rejection(learner_id, proposal, analysis, evidence)
        if rejection is not None:
            return rejection
        error = analysis.errors[proposal.error_index]
        inserted = self.repository.record_error(
            learner_id, request_id, proposal.error_index, error.expression,
            error.category.value, error.suggestion, error.confidence,
        )
        return self._stored_result(learner_id, proposal, inserted)

    def update_many(self, *, learner_id: str, request_id: str,
                    proposals: list[ProfileUpdateProposal], analysis: LanguageAnalysis,
                    evidence: dict[int, list[SearchMatch]]) -> list[ToolResult]:
        results: list[ToolResult | None] = [None] * len(proposals)
        valid: list[tuple[int, ProfileUpdateProposal]] = []
        records: list[tuple[str, str, int, str, str, str, float]] = []
        for position, proposal in enumerate(proposals):
            rejection = self._rejection(learner_id, proposal, analysis, evidence.get(proposal.error_index, []))
            if rejection is not None:
                results[position] = rejection
                continue
            error = analysis.errors[proposal.error_index]
            valid.append((position, proposal))
            records.append((learner_id, request_id, proposal.error_index, error.expression,
                            error.category.value, error.suggestion, error.confidence))
        for (position, proposal), inserted in zip(valid, self.repository.record_errors_batch(records)):
            results[position] = self._stored_result(learner_id, proposal, inserted)
        return [result for result in results if result is not None]
