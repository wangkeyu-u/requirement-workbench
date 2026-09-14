"""Application service layer: incremental analysis and reply guardrails."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from .database import Database, json_dumps, json_loads, utc_now
from .models import (
    ANSWERABLE_REQUIREMENT_FIELDS,
    REPLY_MIN_COMPLETENESS,
    REQUIREMENT_FIELDS,
    REQUIREMENT_LIST_FIELDS,
    calculate_completeness,
    normalize_requirement_state,
)
from .providers import (
    IncomingMail,
    LLMProvider,
    MailProviderError,
    MailProvider,
    QuestionSuggestion,
    configured_mail_label,
    configured_llm_label,
    LLMProviderError,
    resolve_llm_provider,
    resolve_mail_provider,
    validate_analysis_result,
    validate_question_result,
)


def _bool(value: Any) -> bool:
    return bool(int(value)) if isinstance(value, (int, float, str)) else bool(value)


def _thread_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "sender": row["sender"],
        "subject": row["subject"],
        "preview": row["preview"],
        "status": row["status"],
        "completeness": int(row["completeness"]),
        "unread_count": int(row["unread_count"]),
        "question_count": int(row["question_count"]),
        "updated_at": row["updated_at"],
        "do_not_reply": _bool(row["do_not_reply"]),
        "requirement_id": row["requirement_id"],
        "category": row["category"],
    }


def _attachment_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "size": int(row["size"]),
    }


def _email_from_row(row: Any, attachments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "sender": row["sender"],
        "sender_email": row["sender_email"],
        "subject": row["subject"],
        "body": row["body"],
        "received_at": row["received_at"],
        "direction": row["direction"],
        "do_not_reply": _bool(row["do_not_reply"]),
        "attachments": attachments,
    }


#: The only email fields a model provider may ever receive.
MODEL_SAFE_EMAIL_FIELDS = ("sender", "sender_email", "subject", "body", "received_at", "direction")
#: The only attachment fields a model provider may ever receive. Never the bytes.
MODEL_SAFE_ATTACHMENT_FIELDS = ("filename", "content_type", "size")


def _model_safe_email(email: dict[str, Any]) -> dict[str, Any]:
    """Drop everything a model must not see.

    PRODUCT.md section 12 forbids the AI from reading attachment contents, so the
    projection is enforced here instead of relying on callers to behave.
    """

    return {
        **{field: email[field] for field in MODEL_SAFE_EMAIL_FIELDS},
        "attachments": [
            {field: attachment[field] for field in MODEL_SAFE_ATTACHMENT_FIELDS}
            for attachment in email["attachments"]
        ],
    }


def _requirement_from_row(row: Any, thread: dict[str, Any]) -> dict[str, Any]:
    state = normalize_requirement_state(
        json_loads(row["state_json"], {}), row["id"], thread.get("title", "")
    )
    state["status"] = row["status"]
    state["completeness"] = int(row["completeness"])
    return state


def _question_from_row(row: Any | None) -> dict[str, str] | None:
    if row is None:
        return None
    return {"field": row["field"], "text": row["text"]}


def _reply_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "body": row["body"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


class WorkbenchService:
    def __init__(self, database: Database) -> None:
        self.db = database

    def _settings_row(self, conn: Any) -> Any:
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        if row is None:
            raise HTTPException(status_code=500, detail="Settings are not initialized")
        return row

    def settings(self) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = self._settings_row(conn)
            configured_llm = row["llm_provider"]
            configured_mail = str(row["mail_provider"]).strip().lower() or "mock"
            return {
                "auto_reply": _bool(row["auto_reply"]),
                "llm_provider": configured_llm_label(configured_llm),
                "mail_provider": configured_mail_label(configured_mail),
            }

    def update_settings(self, auto_reply: bool) -> dict[str, Any]:
        # Read the pending question and build the provider context without a
        # write transaction. The provider may take tens of seconds, so the
        # user's answer must not hold SQLite's RESERVED lock while we wait.
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE settings SET auto_reply = ?, updated_at = ? WHERE id = 1",
                (int(auto_reply), utc_now()),
            )
        return self.settings()

    def list_threads(self) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM threads ORDER BY updated_at DESC, id ASC").fetchall()
            return [_thread_from_row(row) for row in rows]

    @staticmethod
    def _mail_thread_id(message: IncomingMail) -> str:
        key = message.thread_key.strip() or message.message_key.strip()
        return f"mail-thread-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]}"

    @staticmethod
    def _mail_email_id(message: IncomingMail, provider: str) -> str:
        key = f"{provider}:{message.message_key.strip()}"
        return f"mail-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:28]}"

    def sync_mailbox(self) -> dict[str, Any]:
        """Fetch new messages from the configured mailbox and persist them idempotently."""

        with self.db.connection() as conn:
            settings = self._settings_row(conn)
            configured_provider = str(settings["mail_provider"]).strip().lower() or "mock"
        try:
            provider = resolve_mail_provider(configured_provider)
        except MailProviderError as exc:
            raise HTTPException(status_code=502, detail=f"Mail provider error: {exc}") from exc
        if configured_provider == "mock":
            return {"provider": "mock", "fetched": 0, "imported": 0, "skipped": 0, "threads": 0}
        try:
            messages = provider.fetch_messages()
        except MailProviderError as exc:
            raise HTTPException(status_code=502, detail=f"Mail provider error: {exc}") from exc

        imported = 0
        skipped = 0
        touched_threads: set[str] = set()
        with self.db.transaction() as conn:
            for message in messages:
                email_id = self._mail_email_id(message, configured_provider)
                if conn.execute("SELECT 1 FROM emails WHERE id = ?", (email_id,)).fetchone() is not None:
                    skipped += 1
                    continue
                thread_id = self._mail_thread_id(message)
                thread_row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
                if thread_row is None:
                    requirement_id = f"req-{hashlib.sha256(thread_id.encode('utf-8')).hexdigest()[:24]}"
                    requirement = normalize_requirement_state(
                        {"title": message.subject, "requester": message.sender},
                        requirement_id,
                        message.subject,
                    )
                    requirement["completeness"] = calculate_completeness(requirement)
                    conn.execute(
                        """
                        INSERT INTO threads(
                            id, title, sender, subject, preview, status, completeness,
                            unread_count, question_count, updated_at, do_not_reply,
                            requirement_id, category
                        ) VALUES (?, ?, ?, ?, ?, 'waiting_for_me', ?, 1, 0, ?, 0, ?, 'requirement')
                        """,
                        (
                            thread_id,
                            message.subject,
                            message.sender,
                            message.subject,
                            message.body.replace("\n", " ").strip()[:160],
                            requirement["completeness"],
                            message.received_at,
                            requirement_id,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO requirements(id, thread_id, state_json, status, completeness, updated_at)
                        VALUES (?, ?, ?, 'waiting_for_me', ?, ?)
                        """,
                        (
                            requirement_id,
                            thread_id,
                            json_dumps(requirement),
                            requirement["completeness"],
                            message.received_at,
                        ),
                    )
                else:
                    next_status = thread_row["status"]
                    if next_status not in {"do_not_reply", "no_action"}:
                        next_status = "waiting_for_me"
                    conn.execute(
                        """
                        UPDATE threads
                        SET sender = ?, subject = ?, title = ?, preview = ?, status = ?,
                            unread_count = unread_count + 1, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            message.sender,
                            message.subject,
                            message.subject,
                            message.body.replace("\n", " ").strip()[:160],
                            next_status,
                            message.received_at,
                            thread_id,
                        ),
                    )
                conn.execute(
                    """
                    INSERT INTO emails(
                        id, thread_id, sender, sender_email, subject, body,
                        received_at, direction, do_not_reply
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'inbound', 0)
                    """,
                    (
                        email_id,
                        thread_id,
                        message.sender,
                        message.sender_email,
                        message.subject,
                        message.body,
                        message.received_at,
                    ),
                )
                for index, attachment in enumerate(message.attachments):
                    attachment_id = (
                        f"{email_id}-attachment-{index}-"
                        f"{hashlib.sha256(attachment.filename.encode('utf-8')).hexdigest()[:10]}"
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO attachments(
                            id, email_id, filename, content_type, size, content
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            attachment_id,
                            email_id,
                            attachment.filename,
                            attachment.content_type,
                            len(attachment.content),
                            attachment.content,
                        ),
                    )
                imported += 1
                touched_threads.add(thread_id)
        return {
            "provider": getattr(provider, "label", configured_provider),
            "fetched": len(messages),
            "imported": imported,
            "skipped": skipped,
            "threads": len(touched_threads),
        }

    def _get_thread_row(self, conn: Any, thread_id: str) -> Any:
        row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        return row

    def _get_requirement_row(self, conn: Any, thread_id: str) -> Any:
        row = conn.execute("SELECT * FROM requirements WHERE thread_id = ?", (thread_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=500, detail="Requirement state not found")
        return row

    def _get_emails(self, conn: Any, thread_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT id, thread_id, sender, sender_email, subject, body, received_at, direction, do_not_reply
            FROM emails WHERE thread_id = ? ORDER BY received_at ASC, id ASC
            """,
            (thread_id,),
        ).fetchall()
        if not rows:
            return []
        # One query for the whole thread's attachments instead of one query per email.
        attachment_rows = conn.execute(
            """
            SELECT email_id, id, filename, content_type, size FROM attachments
            WHERE email_id IN (SELECT id FROM emails WHERE thread_id = ?)
            ORDER BY email_id ASC, id ASC
            """,
            (thread_id,),
        ).fetchall()
        by_email: dict[str, list[dict[str, Any]]] = {}
        for item in attachment_rows:
            by_email.setdefault(item["email_id"], []).append(_attachment_from_row(item))
        return [_email_from_row(row, by_email.get(row["id"], [])) for row in rows]

    def _get_model_emails(self, conn: Any, thread_id: str) -> list[dict[str, Any]]:
        """Build the only email context a provider is allowed to see.

        Attachment content is never selected from SQLite, and the projection in
        ``_model_safe_email`` strips any field a model must not receive.
        """

        return [_model_safe_email(email) for email in self._get_emails(conn, thread_id)]

    def detail(self, thread_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            thread = _thread_from_row(self._get_thread_row(conn, thread_id))
            requirement = _requirement_from_row(self._get_requirement_row(conn, thread_id), thread)
            question_row = conn.execute(
                "SELECT field, text FROM questions WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            reply_rows = conn.execute(
                "SELECT id, body, status, created_at FROM replies WHERE thread_id = ? ORDER BY created_at ASC, id ASC",
                (thread_id,),
            ).fetchall()
            return {
                "thread": thread,
                "emails": self._get_emails(conn, thread_id),
                "requirement": requirement,
                "question": _question_from_row(question_row),
                "reply_log": [_reply_from_row(row) for row in reply_rows],
            }

    def _provider_bundle(self, conn: Any) -> tuple[LLMProvider, MailProvider, Any]:
        settings = self._settings_row(conn)
        try:
            llm = resolve_llm_provider(settings["llm_provider"])
            mail = resolve_mail_provider(settings["mail_provider"])
        except MailProviderError as exc:
            raise HTTPException(status_code=502, detail=f"Mail provider error: {exc}") from exc
        return llm, mail, settings

    @staticmethod
    def _status_for(
        *,
        category: str,
        do_not_reply: bool,
        has_question: bool,
        completeness: int,
        has_reply: bool,
    ) -> str:
        if do_not_reply:
            return "do_not_reply"
        if category == "no_action":
            return "no_action"
        if has_reply:
            return "replied"
        if has_question:
            return "waiting_for_me"
        return "ready" if completeness >= REPLY_MIN_COMPLETENESS else "waiting_for_me"

    def _current_status(
        self,
        conn: Any,
        thread_id: str,
        *,
        category: str,
        has_question: bool,
        completeness: int,
    ) -> str:
        """Resolve the display status from the durable reply-blocking state.

        Callers only supply what the database cannot answer. Whether the thread or
        any of its emails is guarded, and whether a reply already went out, is always
        re-read here so the three status-writing paths cannot drift apart.
        """

        thread_guard = _bool(
            conn.execute("SELECT do_not_reply FROM threads WHERE id = ?", (thread_id,)).fetchone()["do_not_reply"]
        )
        email_guard = conn.execute(
            "SELECT 1 FROM emails WHERE thread_id = ? AND do_not_reply = 1 LIMIT 1", (thread_id,)
        ).fetchone() is not None
        has_reply = conn.execute(
            "SELECT 1 FROM replies WHERE thread_id = ? AND status = 'sent' LIMIT 1", (thread_id,)
        ).fetchone() is not None
        return self._status_for(
            category=category,
            do_not_reply=thread_guard or email_guard,
            has_question=has_question,
            completeness=completeness,
            has_reply=has_reply,
        )

    @staticmethod
    def _apply_patch(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        updated = dict(state)
        for field, value in patch.items():
            if field not in REQUIREMENT_FIELDS or field in {"id", "status", "completeness"}:
                continue
            if field in REQUIREMENT_LIST_FIELDS:
                incoming = value if isinstance(value, list) else ([] if value is None else [value])
                existing = list(updated.get(field) or [])
                for item in incoming:
                    item = str(item).strip()
                    if item and item not in existing:
                        existing.append(item)
                updated[field] = existing
            elif not updated.get(field):
                updated[field] = value
        return updated

    @staticmethod
    def _apply_answer(
        state: dict[str, Any],
        field: str,
        answer: str,
        answered_question_text: str,
    ) -> dict[str, Any]:
        """Apply exactly one user answer to a copy of the current state."""

        updated = dict(state)
        if field in REQUIREMENT_LIST_FIELDS:
            existing = list(updated.get(field) or [])
            if answer not in existing:
                existing.append(answer)
            updated[field] = existing
        else:
            updated[field] = answer
        updated["open_questions"] = [
            item for item in list(updated.get("open_questions") or []) if item != answered_question_text
        ]
        return updated

    @staticmethod
    def _provider_http_error(exc: LLMProviderError) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM provider error: {exc}",
        )

    def _save_requirement(
        self,
        conn: Any,
        *,
        thread_id: str,
        state: dict[str, Any],
        category: str,
        question: QuestionSuggestion | None,
        increment_question: bool,
        answered_question_text: str | None = None,
    ) -> None:
        current_question = conn.execute(
            "SELECT field, text FROM questions WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        completeness = calculate_completeness(state) if category == "requirement" else 0
        state["completeness"] = completeness
        state["status"] = self._current_status(
            conn,
            thread_id,
            category=category,
            has_question=question is not None,
            completeness=completeness,
        )
        state["open_questions"] = list(state.get("open_questions") or [])
        if answered_question_text:
            state["open_questions"] = [
                item for item in state["open_questions"] if item != answered_question_text
            ]
        if question is not None and question.text not in state["open_questions"]:
            state["open_questions"].append(question.text)
        conn.execute(
            """
            UPDATE requirements
            SET state_json = ?, status = ?, completeness = ?, updated_at = ?
            WHERE thread_id = ?
            """,
            (json_dumps(state), state["status"], completeness, utc_now(), thread_id),
        )
        if question is None:
            conn.execute("DELETE FROM questions WHERE thread_id = ?", (thread_id,))
        else:
            is_new = current_question is None or current_question["field"] != question.field or current_question["text"] != question.text
            conn.execute(
                """
                INSERT INTO questions(thread_id, field, text, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET field = excluded.field, text = excluded.text
                """,
                (thread_id, question.field, question.text, utc_now()),
            )
            if is_new:
                conn.execute(
                    """
                    INSERT INTO clarification_messages(id, thread_id, role, field, text, created_at)
                    VALUES (?, ?, 'assistant', ?, ?, ?)
                    """,
                    (
                        f"clarification-question-{uuid.uuid4().hex}",
                        thread_id,
                        question.field,
                        question.text,
                        utc_now(),
                    ),
                )
            increment_question = increment_question or is_new
        updated_at = utc_now()
        conn.execute(
            """
            UPDATE threads
            SET category = ?, status = ?, completeness = ?, question_count = question_count + ?, updated_at = ?
            WHERE id = ?
            """,
            (category, state["status"], completeness, int(bool(increment_question)), updated_at, thread_id),
        )

    def analyze(self, thread_id: str) -> dict[str, Any]:
        # Read a consistent-enough snapshot, then call the external provider
        # without holding SQLite's RESERVED write lock. A DeepSeek request can
        # take up to 45 seconds; keeping BEGIN IMMEDIATE open that long would
        # make unrelated writes hit the 30-second busy timeout.
        with self.db.connection() as conn:
            thread_row = self._get_thread_row(conn, thread_id)
            thread = _thread_from_row(thread_row)
            requirement_row = self._get_requirement_row(conn, thread_id)
            state = _requirement_from_row(requirement_row, thread)
            emails = self._get_model_emails(conn, thread_id)
            llm, _, _ = self._provider_bundle(conn)
            current_question_row = conn.execute(
                "SELECT field, text FROM questions WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        try:
            result = validate_analysis_result(llm.analyze(thread, emails, state))
            state_after_patch = self._apply_patch(state, result.patch)
            category = result.category
            # A current user question remains authoritative until the user answers it.
            if current_question_row is not None:
                candidate_question = QuestionSuggestion(
                    current_question_row["field"], current_question_row["text"]
                )
            else:
                candidate_question = result.question
                if candidate_question is None and category == "requirement":
                    candidate_question = validate_question_result(
                        llm.suggest_question(thread, emails, state_after_patch)
                    )
        except LLMProviderError as exc:
            raise self._provider_http_error(exc) from exc

        with self.db.transaction() as conn:
            # Re-read before writing so a concurrent local update is preserved.
            latest_thread = self._get_thread_row(conn, thread_id)
            latest_thread_data = _thread_from_row(latest_thread)
            latest_requirement = self._get_requirement_row(conn, thread_id)
            latest_state = _requirement_from_row(latest_requirement, latest_thread_data)
            state_to_save = self._apply_patch(latest_state, result.patch)
            latest_question = conn.execute(
                "SELECT field, text FROM questions WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            if latest_question is not None:
                question = QuestionSuggestion(latest_question["field"], latest_question["text"])
                increment = False
            else:
                question = candidate_question
                increment = question is not None
            self._save_requirement(
                conn,
                thread_id=thread_id,
                state=state_to_save,
                category=category,
                question=question,
                increment_question=increment,
            )
        return self._auto_reply_if_ready(thread_id, self.detail(thread_id))

    def answer(self, thread_id: str, answer: str) -> dict[str, Any]:
        answer = answer.strip()
        if not answer:
            raise HTTPException(status_code=422, detail="Answer cannot be empty")
        # Read the pending question and build the provider context without a
        # write transaction. The provider may take tens of seconds, so the
        # user's answer must not hold SQLite's RESERVED lock while we wait.
        with self.db.connection() as conn:
            thread_row = self._get_thread_row(conn, thread_id)
            thread = _thread_from_row(thread_row)
            requirement_row = self._get_requirement_row(conn, thread_id)
            state = _requirement_from_row(requirement_row, thread)
            question_row = conn.execute(
                "SELECT field, text FROM questions WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            if question_row is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This thread has no pending question")
            field = question_row["field"]
            if field not in ANSWERABLE_REQUIREMENT_FIELDS:
                raise HTTPException(status_code=500, detail="Question field is not supported")
            question_text = question_row["text"]
            emails = self._get_model_emails(conn, thread_id)
            llm, _, _ = self._provider_bundle(conn)

        tentative_state = self._apply_answer(state, field, answer, question_text)
        try:
            next_question = validate_question_result(
                llm.suggest_question(thread, emails, tentative_state)
            )
        except LLMProviderError as exc:
            # Keep the pending question and the user's answer out of the
            # database when the provider cannot produce a safe next step.
            raise self._provider_http_error(exc) from exc

        with self.db.transaction() as conn:
            latest_thread = self._get_thread_row(conn, thread_id)
            latest_thread_data = _thread_from_row(latest_thread)
            latest_requirement = self._get_requirement_row(conn, thread_id)
            latest_state = _requirement_from_row(latest_requirement, latest_thread_data)
            latest_question = conn.execute(
                "SELECT field, text FROM questions WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            if latest_question is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This thread no longer has the question you answered",
                )
            if latest_question["field"] != field or latest_question["text"] != question_text:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The pending question changed; reload before answering",
                )
            state_to_save = self._apply_answer(
                latest_state, field, answer, latest_question["text"]
            )
            conn.execute(
                """
                INSERT INTO clarification_messages(id, thread_id, role, field, text, created_at)
                VALUES (?, ?, 'user', ?, ?, ?)
                """,
                (f"clarification-answer-{uuid.uuid4().hex}", thread_id, field, answer, utc_now()),
            )
            conn.execute(
                "DELETE FROM questions WHERE thread_id = ?",
                (thread_id,),
            )
            self._save_requirement(
                conn,
                thread_id=thread_id,
                state=state_to_save,
                category=latest_thread_data["category"],
                question=next_question,
                increment_question=next_question is not None,
                answered_question_text=latest_question["text"],
            )
        return self._auto_reply_if_ready(thread_id, self.detail(thread_id))

    def _auto_reply_if_ready(self, thread_id: str, detail: dict[str, Any]) -> dict[str, Any]:
        """Run the same guarded send path used by the explicit reply endpoint."""

        thread = detail["thread"]
        if (
            thread["category"] != "requirement"
            or thread["status"] != "ready"
            or detail["question"] is not None
            or thread["do_not_reply"]
            or any(email["do_not_reply"] for email in detail["emails"])
            or detail["reply_log"]
        ):
            return detail
        with self.db.connection() as conn:
            settings = self._settings_row(conn)
            auto_reply = _bool(settings["auto_reply"])
        if not auto_reply:
            return detail
        try:
            return self.send_reply(thread_id)
        except HTTPException as exc:
            # A concurrent request may have won the guarded send. Return the
            # durable state rather than turning a successful analysis/answer
            # into an error. A failed automatic generation is retryable from
            # the explicit reply action after the requirement is saved.
            if exc.status_code in {
                status.HTTP_409_CONFLICT,
                status.HTTP_502_BAD_GATEWAY,
            }:
                return self.detail(thread_id)
            raise

    def update_thread_do_not_reply(self, thread_id: str, do_not_reply: bool) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = self._get_thread_row(conn, thread_id)
            conn.execute(
                "UPDATE threads SET do_not_reply = ?, updated_at = ? WHERE id = ?",
                (int(do_not_reply), utc_now(), thread_id),
            )
            thread = _thread_from_row(row)
            requirement_row = self._get_requirement_row(conn, thread_id)
            state = _requirement_from_row(requirement_row, thread)
            question_row = conn.execute(
                "SELECT field, text FROM questions WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            state["status"] = self._current_status(
                conn,
                thread_id,
                category=thread["category"],
                has_question=question_row is not None,
                completeness=int(state.get("completeness") or 0),
            )
            conn.execute(
                "UPDATE requirements SET state_json = ?, status = ?, updated_at = ? WHERE thread_id = ?",
                (json_dumps(state), state["status"], utc_now(), thread_id),
            )
            conn.execute(
                "UPDATE threads SET status = ?, updated_at = ? WHERE id = ?",
                (state["status"], utc_now(), thread_id),
            )
        return self.detail(thread_id)

    def update_email_do_not_reply(self, email_id: str, do_not_reply: bool) -> dict[str, bool]:
        with self.db.transaction() as conn:
            email = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
            if email is None:
                raise HTTPException(status_code=404, detail="Email not found")
            conn.execute(
                "UPDATE emails SET do_not_reply = ? WHERE id = ?",
                (int(do_not_reply), email_id),
            )
            thread = _thread_from_row(self._get_thread_row(conn, email["thread_id"]))
            requirement = self._get_requirement_row(conn, email["thread_id"])
            state = _requirement_from_row(requirement, thread)
            question = conn.execute(
                "SELECT 1 FROM questions WHERE thread_id = ?", (email["thread_id"],)
            ).fetchone()
            new_status = self._current_status(
                conn,
                email["thread_id"],
                category=thread["category"],
                has_question=question is not None,
                completeness=int(state.get("completeness") or 0),
            )
            state["status"] = new_status
            conn.execute(
                "UPDATE requirements SET state_json = ?, status = ?, updated_at = ? WHERE thread_id = ?",
                (json_dumps(state), new_status, utc_now(), email["thread_id"]),
            )
            conn.execute(
                "UPDATE threads SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, utc_now(), email["thread_id"]),
            )
        return {"ok": True}

    def _reply_blocker(self, conn: Any, thread: dict[str, Any], settings: Any) -> str | None:
        """Return the first reason this thread must not send, or None when it may.

        Every entry maps to a documented guardrail (PRODUCT.md sections 6 and 12) and
        is answered with 409 so the caller learns which rule stopped the send.
        """

        if not _bool(settings["auto_reply"]):
            return "Auto reply is disabled"
        if thread["do_not_reply"]:
            return "Thread is marked DO NOT REPLY"
        if conn.execute(
            "SELECT 1 FROM emails WHERE thread_id = ? AND do_not_reply = 1 LIMIT 1", (thread["id"],)
        ).fetchone() is not None:
            return "An email in this thread is marked DO NOT REPLY"
        if conn.execute(
            "SELECT 1 FROM questions WHERE thread_id = ?", (thread["id"],)
        ).fetchone() is not None:
            return "Answer the pending question before replying"
        if thread["category"] != "requirement":
            return "This thread does not require a reply"
        reply_row = conn.execute(
            "SELECT status FROM replies WHERE thread_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (thread["id"],),
        ).fetchone()
        if reply_row is not None:
            if reply_row["status"] == "sending":
                return "A reply is already in progress for this thread"
            return "A reply was already sent for this thread"
        return None

    def send_reply(self, thread_id: str, requested_body: str | None = None) -> dict[str, Any]:
        # Validate durable guards and collect the model context without holding
        # a write lock while an external LLM request is in flight.
        with self.db.connection() as conn:
            thread = _thread_from_row(self._get_thread_row(conn, thread_id))
            settings = self._settings_row(conn)
            blocker = self._reply_blocker(conn, thread, settings)
            if blocker is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=blocker)
            requirement_row = self._get_requirement_row(conn, thread_id)
            state = _requirement_from_row(requirement_row, thread)
            if int(state.get("completeness") or 0) < REPLY_MIN_COMPLETENESS:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Requirement is not ready to reply")
            emails = self._get_model_emails(conn, thread_id)
            llm, mail, _ = self._provider_bundle(conn)

        if (requested_body or "").strip():
            body = requested_body.strip()
        else:
            try:
                body = llm.generate_reply(thread, emails, state)
            except LLMProviderError as exc:
                raise self._provider_http_error(exc) from exc
        if not isinstance(body, str) or not body.strip():
            raise HTTPException(status_code=500, detail="Reply provider returned an empty body")
        body = body.strip()

        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        reply_id = f"reply-{uuid.uuid4().hex}"
        created_at = utc_now()
        with self.db.transaction() as conn:
            # Reserve the send in a short transaction. The network side effect
            # happens after this transaction commits, so SMTP latency never
            # holds SQLite's write lock.
            latest_thread = _thread_from_row(self._get_thread_row(conn, thread_id))
            settings = self._settings_row(conn)
            blocker = self._reply_blocker(conn, latest_thread, settings)
            if blocker is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=blocker)
            latest_requirement = self._get_requirement_row(conn, thread_id)
            latest_state = _requirement_from_row(latest_requirement, latest_thread)
            if int(latest_state.get("completeness") or 0) < REPLY_MIN_COMPLETENESS:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Requirement is not ready to reply")
            duplicate = conn.execute(
                "SELECT 1 FROM replies WHERE thread_id = ? AND body_hash = ?", (thread_id, body_hash)
            ).fetchone()
            if duplicate is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate reply blocked")
            latest_inbound = conn.execute(
                "SELECT sender_email, subject FROM emails WHERE thread_id = ? AND direction = 'inbound' ORDER BY received_at DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
            recipient = latest_inbound["sender_email"] if latest_inbound else latest_thread["sender"]
            subject = latest_inbound["subject"] if latest_inbound else latest_thread["subject"]
            outbound_sender_email = str(getattr(mail, "from_address", "me@localhost") or "me@localhost")
            outbound_sender = "Requirement Workbench" if getattr(mail, "label", "mock") == "mock" else outbound_sender_email
            conn.execute(
                """
                INSERT INTO replies(id, thread_id, body, status, created_at, body_hash, provider_message_id)
                VALUES (?, ?, ?, 'sending', ?, ?, NULL)
                """,
                (reply_id, thread_id, body, created_at, body_hash),
            )

        try:
            provider_message_id = mail.send_message(
                thread=latest_thread,
                recipient=recipient,
                subject=f"Re: {subject.removeprefix('Re: ').strip()}",
                body=body,
            )
        except MailProviderError as exc:
            with self.db.transaction() as conn:
                conn.execute("DELETE FROM replies WHERE id = ? AND status = 'sending'", (reply_id,))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Mail provider error: {exc}") from exc

        with self.db.transaction() as conn:
            latest_thread = _thread_from_row(self._get_thread_row(conn, thread_id))
            latest_requirement = self._get_requirement_row(conn, thread_id)
            latest_state = _requirement_from_row(latest_requirement, latest_thread)
            conn.execute(
                "UPDATE replies SET status = 'sent', provider_message_id = ? WHERE id = ? AND status = 'sending'",
                (provider_message_id, reply_id),
            )
            outbound_id = f"email-{reply_id}"
            conn.execute(
                """
                INSERT INTO emails(
                    id, thread_id, sender, sender_email, subject, body,
                    received_at, direction, do_not_reply
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'outbound', 0)
                """,
                (
                    outbound_id,
                    thread_id,
                    outbound_sender,
                    outbound_sender_email,
                    f"Re: {subject.removeprefix('Re: ').strip()}",
                    body,
                    created_at,
                ),
            )
            latest_state["status"] = "replied"
            conn.execute(
                "UPDATE requirements SET state_json = ?, status = 'replied', updated_at = ? WHERE thread_id = ?",
                (json_dumps(latest_state), created_at, thread_id),
            )
            conn.execute(
                "UPDATE threads SET status = 'replied', updated_at = ? WHERE id = ?",
                (created_at, thread_id),
            )
        return self.detail(thread_id)

    def requirement_markdown(self, requirement_id: str) -> str:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM requirements WHERE id = ?", (requirement_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Requirement not found")
            thread = _thread_from_row(self._get_thread_row(conn, row["thread_id"]))
            state = _requirement_from_row(row, thread)
            return render_requirement_markdown(state)

    def attachment(self, attachment_id: str) -> tuple[dict[str, Any], bytes]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Attachment not found")
            return (
                {
                    "id": row["id"],
                    "filename": row["filename"],
                    "content_type": row["content_type"],
                    "size": int(row["size"]),
                },
                bytes(row["content"]),
            )


def _markdown_value(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value) if value else "_未填写_"
    if value is None or value == "":
        return "_未填写_"
    return str(value)


def render_requirement_markdown(state: dict[str, Any]) -> str:
    lines = [f"# {state.get('title') or 'Untitled Requirement'}", ""]
    scalar_sections = (
        ("背景", "background"),
        ("业务问题", "business_problem"),
        ("业务目标", "goal"),
        ("相关方", "stakeholders"),
        ("使用者", "users"),
        ("范围", "scope"),
        ("范围外", "out_of_scope"),
    )
    for heading, field in scalar_sections:
        lines.extend([f"## {heading}", _markdown_value(state.get(field)), ""])

    lines.extend(["## 主要功能", ""])
    functional = state.get("functional_requirements") or []
    if functional:
        for index, item in enumerate(functional, start=1):
            lines.extend([f"### FR-{index:03d}", str(item), ""])
    else:
        lines.extend(["_未填写_", ""])

    lines.extend(["## 非功能要求", ""])
    nonfunctional = state.get("non_functional_requirements") or []
    if nonfunctional:
        for index, item in enumerate(nonfunctional, start=1):
            lines.extend([f"### NFR-{index:03d}", str(item), ""])
    else:
        lines.extend(["_未填写_", ""])

    for heading, field in (
        ("约束条件", "constraints"),
        ("依赖项", "dependencies"),
        ("数据来源", "data_sources"),
        ("截止时间", "deadline"),
        ("优先级", "priority"),
    ):
        lines.extend([f"## {heading}", _markdown_value(state.get(field)), ""])

    lines.extend(["## 验收标准", ""])
    criteria = state.get("acceptance_criteria") or []
    if criteria:
        for index, item in enumerate(criteria, start=1):
            lines.extend([f"### AC-{index:03d}", str(item), ""])
    else:
        lines.extend(["_未填写_", ""])

    for heading, field in (("假设", "assumptions"), ("风险", "risks"), ("待确认问题", "open_questions")):
        lines.extend([f"## {heading}", _markdown_value(state.get(field)), ""])
    return "\n".join(lines).rstrip() + "\n"
