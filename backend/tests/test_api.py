from __future__ import annotations

import asyncio
import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from unittest.mock import patch

from backend.app import create_app
from backend.models import calculate_completeness
from backend.providers import (
    AnalysisResult,
    DeepSeekProvider,
    IncomingAttachment,
    IncomingMail,
    IMAPSMTPMailProvider,
    LLMProviderError,
    QuestionSuggestion,
    resolve_llm_provider,
)


async def _asgi_request(
    app: Any,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    headers = [(b"host", b"testserver")]
    if payload is not None:
        headers.append((b"content-type", b"application/json"))
    headers.extend(
        (key.lower().encode("ascii"), value.encode("ascii"))
        for key, value in (extra_headers or {}).items()
    )
    messages: list[dict[str, Any]] = []
    received = False

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "path": path.split("?", 1)[0],
            "raw_path": path.encode("ascii"),
            "query_string": path.split("?", 1)[1].encode("ascii") if "?" in path else b"",
            "headers": headers,
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "root_path": "",
        },
        receive,
        send,
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    chunks = [message.get("body", b"") for message in messages if message["type"] == "http.response.body"]
    raw = b"".join(chunks)
    response_headers = {key.decode(): value.decode() for key, value in start.get("headers", [])}
    if "application/json" in response_headers.get("content-type", "") and raw:
        result: Any = json.loads(raw.decode("utf-8"))
    else:
        result = raw
    return start["status"], response_headers, result


def request(
    app: Any,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], Any]:
    return asyncio.run(_asgi_request(app, method, path, payload, extra_headers))


class WorkbenchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.app = create_app(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_performance_thread_one_question_away(self) -> None:
        """Keep the seeded users question, but make every other field explicit for closure tests."""

        database = self.app.state.database
        with database.transaction() as conn:
            row = conn.execute(
                "SELECT state_json FROM requirements WHERE thread_id = ?",
                ("thread-performance-dashboard",),
            ).fetchone()
            state = json.loads(row["state_json"])
            state.update(
                {
                    "background": "Operations reviews production health across several services.",
                    "business_problem": "Performance regressions are hard to spot across separate telemetry views.",
                    "goal": "Monitor application performance from one operational dashboard.",
                    "stakeholders": ["Platform Engineering"],
                    "users": [],
                    "scope": ["A dashboard for production service performance trends"],
                    "out_of_scope": ["Changing production configuration"],
                    "functional_requirements": ["Show service performance trends"],
                    "non_functional_requirements": ["The dashboard should load quickly"],
                    "constraints": ["Use existing production telemetry"],
                    "dependencies": ["Telemetry service"],
                    "data_sources": ["Production telemetry"],
                    "deadline": "2026-10-31",
                    "priority": "High",
                    "acceptance_criteria": ["Operations can identify a regression from one view"],
                    "assumptions": ["Existing telemetry labels are stable"],
                    "open_questions": ["这个仪表盘会由谁使用？"],
                    "risks": ["Refresh expectations need confirmation."],
                    "status": "waiting_for_me",
                }
            )
            state["completeness"] = calculate_completeness(state)
            conn.execute(
                "UPDATE requirements SET state_json = ?, status = ?, completeness = ? WHERE thread_id = ?",
                (json.dumps(state), state["status"], state["completeness"], "thread-performance-dashboard"),
            )
            conn.execute(
                "UPDATE threads SET status = ?, completeness = ?, do_not_reply = 0 WHERE id = ?",
                (state["status"], state["completeness"], "thread-performance-dashboard"),
            )

    def test_health_and_ten_seed_threads(self) -> None:
        health_status, _, health = request(self.app, "GET", "/api/health")
        self.assertEqual(health_status, 200)
        self.assertEqual(health, {"ok": True})
        status, _, threads = request(self.app, "GET", "/api/threads")
        self.assertEqual(status, 200)
        self.assertEqual(len(threads), 10)
        self.assertEqual({thread["status"] for thread in threads}, {"waiting_for_me", "ready", "do_not_reply", "no_action", "replied"})

    def test_analyze_and_answer_only_updates_current_field(self) -> None:
        status, _, before = request(self.app, "GET", "/api/threads/thread-performance-dashboard")
        self.assertEqual(status, 200)
        old_goal = before["requirement"]["goal"]
        old_scope = before["requirement"]["scope"]
        self.assertEqual(before["question"]["field"], "users")

        status, _, analyzed = request(self.app, "POST", "/api/threads/thread-performance-dashboard/analyze")
        self.assertEqual(status, 200)
        self.assertEqual(analyzed["question"]["field"], "users")
        self.assertEqual(analyzed["requirement"]["goal"], old_goal)

        status, _, answered = request(
            self.app,
            "POST",
            "/api/threads/thread-performance-dashboard/answer",
            {"answer": "Operations team"},
        )
        self.assertEqual(status, 200)
        self.assertIn("Operations team", answered["requirement"]["users"])
        self.assertEqual(answered["requirement"]["goal"], old_goal)
        self.assertEqual(answered["requirement"]["scope"], old_scope)
        self.assertIsNotNone(answered["question"])
        self.assertNotEqual(answered["question"]["field"], "users")

    def test_reanalysis_merges_without_replacing_known_requirement_facts(self) -> None:
        status, _, before = request(self.app, "GET", "/api/threads/thread-performance-dashboard")
        self.assertEqual(status, 200)
        original_functional = before["requirement"]["functional_requirements"]
        status, _, after = request(self.app, "POST", "/api/threads/thread-performance-dashboard/analyze")
        self.assertEqual(status, 200)
        self.assertEqual(after["requirement"]["status"], "waiting_for_me")
        self.assertTrue(set(original_functional).issubset(set(after["requirement"]["functional_requirements"])))

    def test_markdown_and_attachment_metadata_endpoint(self) -> None:
        status, _, markdown = request(self.app, "GET", "/api/requirements/req-customer-export/markdown")
        self.assertEqual(status, 200)
        self.assertIn("# Customer export workflow", markdown["markdown"])
        self.assertIn("### FR-001", markdown["markdown"])
        status, headers, content = request(
            self.app,
            "GET",
            "/api/attachments/attachment-performance-reference?download=true",
        )
        self.assertEqual(status, 200)
        self.assertIn("attachment;", headers["content-disposition"])
        self.assertTrue(content.startswith(b"%PDF-1.4"))
        self.assertIn(b"startxref", content)
        status, _, xlsx_content = request(
            self.app,
            "GET",
            "/api/attachments/attachment-inventory-notes?download=true",
        )
        self.assertEqual(status, 200)
        self.assertTrue(xlsx_content.startswith(b"PK\x03\x04"))
        with zipfile.ZipFile(io.BytesIO(xlsx_content)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("[Content_Types].xml", archive.namelist())
            self.assertIn("xl/workbook.xml", archive.namelist())
            self.assertIn("xl/worksheets/sheet1.xml", archive.namelist())

    def test_global_settings_persist(self) -> None:
        status, _, settings = request(self.app, "GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertTrue(settings["auto_reply"])
        status, _, updated = request(self.app, "PATCH", "/api/settings", {"auto_reply": False})
        self.assertEqual(status, 200)
        self.assertFalse(updated["auto_reply"])
        app_again = create_app(self.database_path)
        status, _, persisted = request(app_again, "GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertFalse(persisted["auto_reply"])

    def test_auto_reply_runs_after_answer_when_ready(self) -> None:
        self._make_performance_thread_one_question_away()
        status, _, answered = request(
            self.app,
            "POST",
            "/api/threads/thread-performance-dashboard/answer",
            {"answer": "Operations team"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(answered["thread"]["status"], "replied")
        self.assertIsNone(answered["question"])
        self.assertNotIn("这个仪表盘会由谁使用？", answered["requirement"]["open_questions"])
        self.assertEqual(len(answered["reply_log"]), 1)
        with self.app.state.database.connection() as conn:
            roles = [
                row["role"]
                for row in conn.execute(
                    "SELECT role FROM clarification_messages WHERE thread_id = ? ORDER BY created_at, id",
                    ("thread-performance-dashboard",),
                ).fetchall()
            ]
        self.assertIn("assistant", roles)
        self.assertIn("user", roles)

    def test_auto_reply_runs_after_analyze_when_already_ready(self) -> None:
        status, _, analyzed = request(
            self.app,
            "POST",
            "/api/threads/thread-customer-export/analyze",
        )
        self.assertEqual(status, 200)
        self.assertEqual(analyzed["thread"]["status"], "replied")
        self.assertEqual(len(analyzed["reply_log"]), 1)

    def test_auto_reply_off_leaves_ready_thread_unsent(self) -> None:
        self._make_performance_thread_one_question_away()
        status, _, _ = request(self.app, "PATCH", "/api/settings", {"auto_reply": False})
        self.assertEqual(status, 200)
        status, _, answered = request(
            self.app,
            "POST",
            "/api/threads/thread-performance-dashboard/answer",
            {"answer": "Operations team"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(answered["thread"]["status"], "ready")
        self.assertEqual(answered["reply_log"], [])

    def test_auto_reply_dnr_leaves_ready_thread_unsent(self) -> None:
        self._make_performance_thread_one_question_away()
        status, _, _ = request(
            self.app,
            "PATCH",
            "/api/threads/thread-performance-dashboard",
            {"do_not_reply": True},
        )
        self.assertEqual(status, 200)
        status, _, answered = request(
            self.app,
            "POST",
            "/api/threads/thread-performance-dashboard/answer",
            {"answer": "Operations team"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(answered["thread"]["status"], "do_not_reply")
        self.assertEqual(answered["reply_log"], [])

    def test_completed_question_stays_deleted_after_restart(self) -> None:
        self._make_performance_thread_one_question_away()
        status, _, answered = request(
            self.app,
            "POST",
            "/api/threads/thread-performance-dashboard/answer",
            {"answer": "Operations team"},
        )
        self.assertEqual(status, 200)
        self.assertIsNone(answered["question"])
        with self.app.state.database.connection() as conn:
            clarification_count = conn.execute(
                "SELECT count(*) FROM clarification_messages WHERE thread_id = ?",
                ("thread-performance-dashboard",),
            ).fetchone()[0]
        self.assertEqual(clarification_count, 2)
        restarted = create_app(self.database_path)
        status, _, after_restart = request(
            restarted,
            "GET",
            "/api/threads/thread-performance-dashboard",
        )
        self.assertEqual(status, 200)
        self.assertIsNone(after_restart["question"])
        self.assertEqual(len(after_restart["reply_log"]), 1)
        with restarted.state.database.connection() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM clarification_messages WHERE thread_id = ?",
                    ("thread-performance-dashboard",),
                ).fetchone()[0],
                2,
            )

    def test_llm_provider_env_switches_existing_database(self) -> None:
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock", "DEEPSEEK_API_KEY": ""}, clear=False):
            create_app(self.database_path)
        with patch.dict(os.environ, {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "test-key"}, clear=False):
            app_with_deepseek = create_app(self.database_path)
            status, _, settings = request(app_with_deepseek, "GET", "/api/settings")
            self.assertEqual(status, 200)
            self.assertEqual(settings["llm_provider"], "deepseek")
            self.assertIsInstance(resolve_llm_provider("deepseek"), DeepSeekProvider)
            with app_with_deepseek.state.database.connection() as conn:
                self.assertEqual(conn.execute("SELECT llm_provider FROM settings WHERE id = 1").fetchone()[0], "deepseek")
        with patch.dict(os.environ, {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": ""}, clear=False):
            fallback_app = create_app(self.database_path)
            status, _, settings = request(fallback_app, "GET", "/api/settings")
            self.assertEqual(status, 200)
            self.assertEqual(settings["llm_provider"], "mock (DeepSeek key missing)")

    def test_configured_deepseek_failure_returns_502(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "deepseek",
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_BASE_URL": "http://127.0.0.1:1",
            },
            clear=False,
        ):
            app = create_app(self.database_path)
            status, _, error = request(app, "POST", "/api/threads/thread-performance-dashboard/analyze")
        self.assertEqual(status, 502)
        self.assertIn("LLM provider error", error["detail"])

    def test_invalid_deepseek_json_returns_502_without_mutating_state(self) -> None:
        status, _, before = request(
            self.app,
            "GET",
            "/api/threads/thread-performance-dashboard",
        )
        self.assertEqual(status, 200)
        invalid_payloads = (
            {
                "category": ["requirement"],
                "patch": {},
                "question": None,
            },
            {
                "category": "requirement",
                "patch": {"goal": ["not", "a", "string"]},
                "question": None,
            },
            {
                "category": "requirement",
                "patch": {},
                "question": {"field": "status", "text": "overwrite status"},
            },
        )
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "test-key"},
            clear=False,
        ):
            app = create_app(self.database_path)
            for payload in invalid_payloads:
                with patch("backend.providers.DeepSeekProvider._chat", return_value=payload):
                    status, _, error = request(
                        app,
                        "POST",
                        "/api/threads/thread-performance-dashboard/analyze",
                    )
                self.assertEqual(status, 502)
                self.assertIn("Invalid LLM output", error["detail"])
                status, _, after = request(
                    app,
                    "GET",
                    "/api/threads/thread-performance-dashboard",
                )
                self.assertEqual(status, 200)
                self.assertEqual(after, before)

    def test_answer_provider_failure_preserves_pending_question_and_state(self) -> None:
        status, _, before = request(
            self.app,
            "GET",
            "/api/threads/thread-performance-dashboard",
        )
        self.assertEqual(status, 200)

        class BrokenQuestionProvider:
            label = "broken-question"

            def analyze(self, thread: dict[str, Any], emails: list[dict[str, Any]], current_state: dict[str, Any]) -> AnalysisResult:
                return AnalysisResult("requirement", {}, None)

            def suggest_question(self, thread: dict[str, Any], emails: list[dict[str, Any]], state: dict[str, Any]) -> QuestionSuggestion | None:
                raise LLMProviderError("synthetic next-question failure")

            def generate_reply(self, thread: dict[str, Any], emails: list[dict[str, Any]], state: dict[str, Any]) -> str:
                return "unused"

        with patch("backend.service.resolve_llm_provider", return_value=BrokenQuestionProvider()):
            status, _, error = request(
                self.app,
                "POST",
                "/api/threads/thread-performance-dashboard/answer",
                {"answer": "Operations team"},
            )
        self.assertEqual(status, 502)
        self.assertIn("synthetic next-question failure", error["detail"])
        status, _, after = request(
            self.app,
            "GET",
            "/api/threads/thread-performance-dashboard",
        )
        self.assertEqual(status, 200)
        self.assertEqual(after, before)

    def test_auto_reply_generation_failure_keeps_saved_answer(self) -> None:
        self._make_performance_thread_one_question_away()

        class BrokenReplyProvider:
            label = "broken-reply"

            def analyze(self, thread: dict[str, Any], emails: list[dict[str, Any]], current_state: dict[str, Any]) -> AnalysisResult:
                return AnalysisResult("requirement", {}, None)

            def suggest_question(self, thread: dict[str, Any], emails: list[dict[str, Any]], state: dict[str, Any]) -> QuestionSuggestion | None:
                return None

            def generate_reply(self, thread: dict[str, Any], emails: list[dict[str, Any]], state: dict[str, Any]) -> str:
                raise LLMProviderError("synthetic reply generation failure")

        with patch("backend.service.resolve_llm_provider", return_value=BrokenReplyProvider()):
            status, _, answered = request(
                self.app,
                "POST",
                "/api/threads/thread-performance-dashboard/answer",
                {"answer": "Operations team"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(answered["thread"]["status"], "ready")
        self.assertIsNone(answered["question"])
        self.assertEqual(answered["reply_log"], [])
        self.assertIn("Operations team", answered["requirement"]["users"])

    def test_provider_call_does_not_run_inside_write_transaction(self) -> None:
        database_path = str(self.database_path)

        class TransactionProbeProvider:
            label = "transaction-probe"

            def analyze(self, thread: dict[str, Any], emails: list[dict[str, Any]], current_state: dict[str, Any]) -> AnalysisResult:
                with sqlite3.connect(database_path, timeout=0.2) as probe:
                    probe.execute("UPDATE settings SET updated_at = updated_at WHERE id = 1")
                return AnalysisResult("requirement", {}, None)

            def suggest_question(self, thread: dict[str, Any], emails: list[dict[str, Any]], state: dict[str, Any]) -> QuestionSuggestion | None:
                return None

            def generate_reply(self, thread: dict[str, Any], emails: list[dict[str, Any]], state: dict[str, Any]) -> str:
                return "unused"

        with patch("backend.service.resolve_llm_provider", return_value=TransactionProbeProvider()):
            status, _, analyzed = request(
                self.app,
                "POST",
                "/api/threads/thread-performance-dashboard/analyze",
            )
        self.assertEqual(status, 200)
        self.assertEqual(analyzed["question"]["field"], "users")

    def test_cors_allows_only_local_configured_frontend_port(self) -> None:
        with patch.dict(os.environ, {"FRONTEND_PORT": "4567"}, clear=False):
            app = create_app(self.database_path)
            for origin in ("http://localhost:4567", "http://127.0.0.1:4567"):
                status, headers, _ = request(
                    app,
                    "OPTIONS",
                    "/api/health",
                    extra_headers={
                        "origin": origin,
                        "access-control-request-method": "GET",
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(headers["access-control-allow-origin"], origin)

            status, headers, _ = request(
                app,
                "OPTIONS",
                "/api/health",
                extra_headers={
                    "origin": "http://localhost:4568",
                    "access-control-request-method": "GET",
                },
            )
            self.assertEqual(status, 400)
            self.assertNotIn("access-control-allow-origin", headers)

    def test_do_not_reply_is_enforced_for_thread_and_email(self) -> None:
        status, _, _ = request(
            self.app,
            "PATCH",
            "/api/threads/thread-customer-export",
            {"do_not_reply": True},
        )
        self.assertEqual(status, 200)
        status, _, error = request(self.app, "POST", "/api/threads/thread-customer-export/reply")
        self.assertEqual(status, 409)
        self.assertIn("DO NOT REPLY", error["detail"])

        status, _, _ = request(
            self.app,
            "PATCH",
            "/api/threads/thread-customer-export",
            {"do_not_reply": False},
        )
        self.assertEqual(status, 200)
        status, _, patch_result = request(
            self.app,
            "PATCH",
            "/api/emails/email-customer-export-1",
            {"do_not_reply": True},
        )
        self.assertEqual(status, 200)
        self.assertEqual(patch_result, {"ok": True})
        status, _, error = request(self.app, "POST", "/api/threads/thread-customer-export/reply")
        self.assertEqual(status, 409)
        self.assertIn("email", error["detail"])

    def test_duplicate_mock_send_is_blocked(self) -> None:
        status, _, first = request(self.app, "POST", "/api/threads/thread-customer-export/reply")
        self.assertEqual(status, 200)
        self.assertEqual(len(first["reply_log"]), 1)
        self.assertEqual(first["thread"]["status"], "replied")
        status, _, error = request(self.app, "POST", "/api/threads/thread-customer-export/reply")
        self.assertEqual(status, 409)
        self.assertIn("already sent", error["detail"])
        status, _, detail = request(self.app, "GET", "/api/threads/thread-customer-export")
        self.assertEqual(status, 200)
        self.assertEqual(len(detail["reply_log"]), 1)

    def test_mail_send_happens_outside_sqlite_write_transaction(self) -> None:
        self._make_performance_thread_one_question_away()
        database_path = str(self.database_path)
        with self.app.state.database.transaction() as conn:
            row = conn.execute(
                "SELECT state_json FROM requirements WHERE thread_id = ?",
                ("thread-performance-dashboard",),
            ).fetchone()
            state = json.loads(row["state_json"])
            state["users"] = ["Operations team"]
            state["open_questions"] = []
            state["status"] = "ready"
            state["completeness"] = calculate_completeness(state)
            conn.execute(
                "UPDATE requirements SET state_json = ?, status = 'ready', completeness = ? WHERE thread_id = ?",
                (json.dumps(state), state["completeness"], "thread-performance-dashboard"),
            )
            conn.execute("DELETE FROM questions WHERE thread_id = ?", ("thread-performance-dashboard",))
            conn.execute(
                "UPDATE threads SET status = 'ready', completeness = ? WHERE id = ?",
                (state["completeness"], "thread-performance-dashboard"),
            )

        class MailProbe:
            label = "imap/smtp"
            from_address = "me@example.com"

            def fetch_messages(self) -> list[IncomingMail]:
                return []

            def send_message(self, **_: Any) -> str:
                with sqlite3.connect(database_path, timeout=0.2) as probe:
                    probe.execute("BEGIN IMMEDIATE")
                    probe.execute("UPDATE settings SET updated_at = updated_at WHERE id = 1")
                    probe.commit()
                return "probe-message-1"

        with patch("backend.service.resolve_mail_provider", return_value=MailProbe()):
            status, _, detail = request(
                self.app,
                "POST",
                "/api/threads/thread-performance-dashboard/reply",
                {"body": "Thanks, we will review this request."},
            )
        self.assertEqual(status, 200)
        self.assertEqual(detail["reply_log"][0]["status"], "sent")
        self.assertEqual(detail["emails"][-1]["sender_email"], "me@example.com")

    def test_real_mail_sync_imports_messages_and_is_idempotent(self) -> None:
        incoming = IncomingMail(
            message_key="<real-message-1@example.com>",
            thread_key="<real-thread@example.com>",
            sender="Ada Lovelace",
            sender_email="ada@example.com",
            subject="Request: Metrics export",
            body="Please export the weekly metrics.",
            received_at="2026-09-14T04:00:00+00:00",
            attachments=(IncomingAttachment("metrics.csv", "text/csv", b"week,total\n1,42\n"),),
        )

        class FakeMailbox:
            label = "imap/smtp"

            def fetch_messages(self) -> list[IncomingMail]:
                return [incoming]

            def send_message(self, **_: Any) -> str:
                return "unused"

        with patch.dict(os.environ, {"MAIL_PROVIDER": "imap"}, clear=False):
            app = create_app(self.database_path)
            with patch("backend.service.resolve_mail_provider", return_value=FakeMailbox()):
                status, _, first = request(app, "POST", "/api/mail/sync")
                self.assertEqual(status, 200)
                self.assertEqual(first["imported"], 1)
                self.assertEqual(first["threads"], 1)
                status, _, second = request(app, "POST", "/api/mail/sync")
                self.assertEqual(status, 200)
                self.assertEqual(second["imported"], 0)
                self.assertEqual(second["skipped"], 1)

        thread_id = app.state.service._mail_thread_id(incoming)
        status, _, detail = request(app, "GET", f"/api/threads/{thread_id}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["thread"]["sender"], "Ada Lovelace")
        self.assertEqual(detail["emails"][0]["body"], incoming.body)
        self.assertEqual(detail["emails"][0]["attachments"][0]["filename"], "metrics.csv")
        self.assertEqual(detail["emails"][0]["attachments"][0]["size"], len(b"week,total\n1,42\n"))

    def test_real_mail_parser_keeps_body_and_attachment_metadata(self) -> None:
        message = EmailMessage()
        message["Message-ID"] = "<parser-message@example.com>"
        message["From"] = "Ada Lovelace <ada@example.com>"
        message["Subject"] = "Request: Weekly metrics"
        message["Date"] = "Mon, 14 Sep 2026 04:00:00 +0000"
        message.set_content("Please keep this original message body.")
        message.add_attachment(
            b"week,total\n1,42\n",
            maintype="text",
            subtype="csv",
            filename="metrics.csv",
        )
        parsed = IMAPSMTPMailProvider._parse_message(message, "7")
        self.assertEqual(parsed.message_key, "<parser-message@example.com>")
        self.assertEqual(parsed.sender_email, "ada@example.com")
        self.assertIn("original message body", parsed.body)
        self.assertEqual(parsed.attachments[0].filename, "metrics.csv")
        self.assertEqual(parsed.attachments[0].content, b"week,total\n1,42\n")

    def test_real_mail_sync_reports_missing_configuration(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MAIL_PROVIDER": "imap",
                "MAIL_IMAP_HOST": "",
                "MAIL_IMAP_USERNAME": "",
                "MAIL_IMAP_PASSWORD": "",
                "MAIL_SMTP_HOST": "",
            },
            clear=False,
        ):
            app = create_app(self.database_path)
            status, _, error = request(app, "POST", "/api/mail/sync")
        self.assertEqual(status, 502)
        self.assertIn("MAIL_IMAP_HOST", error["detail"])


if __name__ == "__main__":
    unittest.main()
