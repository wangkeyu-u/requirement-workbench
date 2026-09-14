"""SQLite schema, initialization, and idempotent demo seeding."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import calculate_completeness, normalize_requirement_state
from .providers import MockMailProvider


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = ROOT / "data" / "requirement_workbench.sqlite3"

DEMO_QUESTION_LOCALIZATION = {
    "thread-performance-dashboard": ("Who will use this dashboard?", "这个仪表盘会由谁使用？"),
    "thread-onboarding-refresh": (
        "Which customer segment is in scope for the onboarding refresh?",
        "这次改版要覆盖哪些客户群体？",
    ),
    "thread-incident-routing": (
        "How should we verify that an alert was routed successfully?",
        "如何确认告警已经成功路由？",
    ),
    "thread-partner-portal": (
        "Should the first version include invitation creation as well as review?",
        "第一版除了审核，是否还要包含创建邀请？",
    ),
    "thread-warehouse-realtime": (
        "What refresh interval should real-time mean?",
        "这里说的“实时”需要多长的刷新间隔？",
    ),
}

#: Schema statements, applied in order.
#:
#: These are executed one by one inside the initialisation transaction rather than
#: through ``executescript``. ``executescript`` implicitly commits any pending
#: transaction before it runs, which would silently turn the schema bootstrap into
#: autocommit and could leave a half-built schema behind if the process died partway.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        auto_reply INTEGER NOT NULL DEFAULT 1,
        llm_provider TEXT NOT NULL DEFAULT 'mock',
        mail_provider TEXT NOT NULL DEFAULT 'mock',
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS threads (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        sender TEXT NOT NULL,
        subject TEXT NOT NULL,
        preview TEXT NOT NULL,
        status TEXT NOT NULL,
        completeness INTEGER NOT NULL DEFAULT 0,
        unread_count INTEGER NOT NULL DEFAULT 0,
        question_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        do_not_reply INTEGER NOT NULL DEFAULT 0,
        requirement_id TEXT NOT NULL UNIQUE,
        category TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS emails (
        id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
        sender TEXT NOT NULL,
        sender_email TEXT NOT NULL,
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        received_at TEXT NOT NULL,
        direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
        do_not_reply INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attachments (
        id TEXT PRIMARY KEY,
        email_id TEXT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        content_type TEXT NOT NULL,
        size INTEGER NOT NULL,
        content BLOB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS requirements (
        id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL UNIQUE REFERENCES threads(id) ON DELETE CASCADE,
        state_json TEXT NOT NULL,
        status TEXT NOT NULL,
        completeness INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS questions (
        thread_id TEXT PRIMARY KEY REFERENCES threads(id) ON DELETE CASCADE,
        field TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clarification_messages (
        id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('assistant', 'user')),
        field TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS replies (
        id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        body_hash TEXT NOT NULL,
        provider_message_id TEXT,
        UNIQUE(thread_id, body_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_emails_thread_received ON emails(thread_id, received_at)",
    "CREATE INDEX IF NOT EXISTS idx_attachments_email ON attachments(email_id)",
    "CREATE INDEX IF NOT EXISTS idx_replies_thread_created ON replies(thread_id, created_at)",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class Database:
    def __init__(self, path: str | Path | None = None) -> None:
        configured = path if path is not None else os.getenv("DATABASE_PATH")
        self.path = str(configured or DEFAULT_DATABASE_PATH)
        self._memory_connection: sqlite3.Connection | None = None

    @property
    def is_memory(self) -> bool:
        return self.path == ":memory:"

    def _new_connection(self) -> sqlite3.Connection:
        if not self.is_memory:
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
            uri=self.path.startswith("file:"),
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        persistent = False
        if self.is_memory:
            if self._memory_connection is None:
                self._memory_connection = self._new_connection()
            conn = self._memory_connection
            persistent = True
        else:
            conn = self._new_connection()
        try:
            yield conn
        finally:
            if not persistent:
                conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def initialize(self) -> None:
        with self.transaction() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            default_llm = os.getenv("LLM_PROVIDER", "mock").strip().lower() or "mock"
            default_mail = os.getenv("MAIL_PROVIDER", "mock").strip().lower() or "mock"
            conn.execute(
                """
                INSERT OR IGNORE INTO settings(id, auto_reply, llm_provider, mail_provider, updated_at)
                VALUES(1, ?, ?, ?, ?)
                """,
                (1, default_llm, default_mail, utc_now()),
            )
            # Provider selection is deployment configuration, while auto_reply is user state.
            # Sync an explicitly supplied provider env var even when this database already exists.
            if "LLM_PROVIDER" in os.environ:
                conn.execute(
                    "UPDATE settings SET llm_provider = ?, updated_at = ? WHERE id = 1",
                    (default_llm, utc_now()),
                )
            if "MAIL_PROVIDER" in os.environ:
                conn.execute(
                    "UPDATE settings SET mail_provider = ?, updated_at = ? WHERE id = 1",
                    (default_mail, utc_now()),
                )

        self._seed_demo_data()
        self._backfill_current_clarification_messages()
        self._localize_demo_questions()

    def _seed_demo_data(self) -> None:
        """Seed the demo mailbox in a single transaction, one thread at a time.

        Keeping the whole seed atomic means a first run either produces the complete
        demo mailbox or nothing at all, instead of a partial mailbox that the next
        run would have to reconcile.
        """

        with self.transaction() as conn:
            for seed in MockMailProvider.seed_threads():
                self._seed_thread(conn, seed)

    def _seed_thread(self, conn: sqlite3.Connection, seed: dict[str, Any]) -> None:
        emails = seed["emails"]
        latest = max(email["received_at"] for email in emails)
        preview = next(
            (email["body"].replace("\n", " ").strip() for email in emails if email["direction"] == "inbound"),
            "",
        )[:160]
        requirement = normalize_requirement_state(
            seed["requirement"], seed["requirement"]["id"], seed["title"]
        )
        requirement["completeness"] = int(
            seed["requirement"].get("completeness") or calculate_completeness(requirement)
        )
        inserted_thread = conn.execute(
            """
            INSERT OR IGNORE INTO threads(
                id, title, sender, subject, preview, status, completeness,
                unread_count, question_count, updated_at, do_not_reply,
                requirement_id, category
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seed["id"],
                seed["title"],
                seed["sender"],
                seed["subject"],
                preview,
                seed["status"],
                requirement["completeness"],
                int(seed.get("unread_count", 0)),
                int(seed.get("question_count", 0)),
                latest,
                int(bool(seed.get("do_not_reply", False))),
                requirement["id"],
                seed["category"],
            ),
        ).rowcount == 1
        # A thread is the seed boundary. If it already exists, do not restore
        # deleted questions or overwrite any user progress on restart.
        if not inserted_thread:
            return
        conn.execute(
            """
            INSERT OR IGNORE INTO requirements(id, thread_id, state_json, status, completeness, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                requirement["id"],
                seed["id"],
                json_dumps(requirement),
                requirement["status"],
                requirement["completeness"],
                latest,
            ),
        )
        for email in emails:
            conn.execute(
                """
                INSERT OR IGNORE INTO emails(
                    id, thread_id, sender, sender_email, subject, body,
                    received_at, direction, do_not_reply
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email["id"],
                    seed["id"],
                    email["sender"],
                    email["sender_email"],
                    email["subject"],
                    email["body"],
                    email["received_at"],
                    email["direction"],
                    int(bool(email.get("do_not_reply", False))),
                ),
            )
            for attachment in email.get("attachments", []):
                content = bytes(attachment.get("content", b""))
                conn.execute(
                    """
                    INSERT OR IGNORE INTO attachments(
                        id, email_id, filename, content_type, size, content
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attachment["id"],
                        email["id"],
                        attachment["filename"],
                        attachment["content_type"],
                        len(content),
                        content,
                    ),
                )
        question = seed.get("question")
        if question:
            inserted_question = conn.execute(
                """
                INSERT OR IGNORE INTO questions(thread_id, field, text, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (seed["id"], question["field"], question["text"], latest),
            ).rowcount == 1
            if inserted_question:
                question_message_id = (
                    f"clarification-question-{seed['id']}-"
                    f"{hashlib.sha256(question['text'].encode('utf-8')).hexdigest()[:12]}"
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO clarification_messages(
                        id, thread_id, role, field, text, created_at
                    ) VALUES (?, ?, 'assistant', ?, ?, ?)
                    """,
                    (
                        question_message_id,
                        seed["id"],
                        question["field"],
                        question["text"],
                        latest,
                    ),
                )
        for reply in seed.get("replies", []):
            conn.execute(
                """
                INSERT OR IGNORE INTO replies(
                    id, thread_id, body, status, created_at, body_hash, provider_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reply["id"],
                    seed["id"],
                    reply["body"],
                    reply["status"],
                    reply["created_at"],
                    hashlib.sha256(reply["body"].encode("utf-8")).hexdigest(),
                    "mock-seed",
                ),
            )

    def _backfill_current_clarification_messages(self) -> None:
        """Give pre-table databases a history row for any still-pending question."""

        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT thread_id, field, text, created_at FROM questions"
            ).fetchall()
            for row in rows:
                message_id = (
                    f"clarification-question-{row['thread_id']}-"
                    f"{hashlib.sha256(row['text'].encode('utf-8')).hexdigest()[:12]}"
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO clarification_messages(
                        id, thread_id, role, field, text, created_at
                    ) VALUES (?, ?, 'assistant', ?, ?, ?)
                    """,
                    (message_id, row["thread_id"], row["field"], row["text"], row["created_at"]),
                )

    def _localize_demo_questions(self) -> None:
        """Migrate older demo databases after the assistant copy was localized."""

        with self.transaction() as conn:
            for thread_id, (old_text, new_text) in DEMO_QUESTION_LOCALIZATION.items():
                conn.execute(
                    "UPDATE questions SET text = ? WHERE thread_id = ? AND text = ?",
                    (new_text, thread_id, old_text),
                )
                conn.execute(
                    """
                    UPDATE clarification_messages
                    SET text = ?
                    WHERE thread_id = ? AND role = 'assistant' AND text = ?
                    """,
                    (new_text, thread_id, old_text),
                )
                row = conn.execute(
                    "SELECT state_json FROM requirements WHERE thread_id = ?", (thread_id,)
                ).fetchone()
                if row is None:
                    continue
                state = json_loads(row["state_json"], {})
                open_questions = state.get("open_questions")
                if not isinstance(open_questions, list):
                    continue
                localized = [new_text if item == old_text else item for item in open_questions]
                if localized != open_questions:
                    conn.execute(
                        "UPDATE requirements SET state_json = ? WHERE thread_id = ?",
                        (json_dumps({**state, "open_questions": localized}), thread_id),
                    )
