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

    def test_real_mailbox_starts_with_auto_reply_off_and_preserves_explicit_choice(self) -> None:
        # An existing demo setting must not silently authorize SMTP on provider switch.
        with patch.dict(os.environ, {"MAIL_PROVIDER": "imap"}, clear=False):
            real_app = create_app(self.database_path)
            status, _, settings = request(real_app, "GET", "/api/settings")
            self.assertEqual(status, 200)
            self.assertFalse(settings["auto_reply"])
            status, _, _ = request(real_app, "PATCH", "/api/settings", {"auto_reply": True})
            self.assertEqual(status, 200)
            restarted = create_app(self.database_path)
            status, _, persisted = request(restarted, "GET", "/api/settings")
            self.assertEqual(status, 200)
            self.assertTrue(persisted["auto_reply"])

        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"MAIL_PROVIDER": "imap"}, clear=False):
                fresh_app = create_app(Path(directory) / "fresh.sqlite3")
                status, _, fresh_settings = request(fresh_app, "GET", "/api/settings")
                self.assertEqual(status, 200)
                self.assertFalse(fresh_settings["auto_reply"])

    def test_manual_mock_reply_works_with_auto_reply_off(self) -> None:
        status, _, _ = request(self.app, "PATCH", "/api/settings", {"auto_reply": False})
        self.assertEqual(status, 200)
        status, _, detail = request(self.app, "POST", "/api/threads/thread-customer-export/reply")
        self.assertEqual(status, 200)
        self.assertEqual(detail["thread"]["status"], "replied")

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

    def test_unknown_send_result_requires_manual_resolution_before_retry(self) -> None:
        class UncertainMailbox:
            label = "mock"

            def send_message(self, *, thread: dict[str, Any], recipient: str, subject: str, body: str) -> str:
                raise RuntimeError("connection dropped after send")

        with patch("backend.service.resolve_mail_provider", return_value=UncertainMailbox()):
            status, _, error = request(self.app, "POST", "/api/threads/thread-customer-export/reply")
        self.assertEqual(status, 502)
        self.assertIn("unknown", error["detail"])
        status, _, detail = request(self.app, "GET", "/api/threads/thread-customer-export")
        self.assertEqual(detail["reply_log"][0]["status"], "uncertain")
        status, _, blocked = request(self.app, "POST", "/api/threads/thread-customer-export/reply")
        self.assertEqual(status, 409)
        self.assertIn("Confirm whether", blocked["detail"])

        status, _, resolved = request(
            self.app,
            "POST",
            "/api/threads/thread-customer-export/reply/resolve",
            {"delivered": False},
        )
        self.assertEqual(status, 200)
        self.assertEqual(resolved["reply_log"], [])
        status, _, retried = request(self.app, "POST", "/api/threads/thread-customer-export/reply")
        self.assertEqual(status, 200)
        self.assertEqual(retried["thread"]["status"], "replied")

    def test_confirming_uncertain_reply_records_it_once(self) -> None:
        class UncertainMailbox:
            label = "mock"

            def send_message(self, *, thread: dict[str, Any], recipient: str, subject: str, body: str) -> str:
                raise RuntimeError("connection dropped after send")

        with patch("backend.service.resolve_mail_provider", return_value=UncertainMailbox()):
            status, _, _ = request(self.app, "POST", "/api/threads/thread-customer-export/reply")
        self.assertEqual(status, 502)
        status, _, resolved = request(
            self.app,
            "POST",
            "/api/threads/thread-customer-export/reply/resolve",
            {"delivered": True},
        )
        self.assertEqual(status, 200)
        self.assertEqual(resolved["thread"]["status"], "replied")
        self.assertEqual(resolved["reply_log"][0]["status"], "sent")
        self.assertEqual(len([email for email in resolved["emails"] if email["direction"] == "outbound"]), 1)
        status, _, _ = request(
            self.app,
            "POST",
            "/api/threads/thread-customer-export/reply/resolve",
            {"delivered": True},
        )
        self.assertEqual(status, 409)

    def test_stale_sending_reply_becomes_uncertain_on_detail_read(self) -> None:
        with self.app.state.database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO replies(id, thread_id, body, status, created_at, body_hash, provider_message_id)
                VALUES ('reply-stale', 'thread-customer-export', 'Draft', 'sending',
                        '2020-01-01T00:00:00+00:00', 'stale-hash', NULL)
                """
            )
        status, _, detail = request(self.app, "GET", "/api/threads/thread-customer-export")
        self.assertEqual(status, 200)
        self.assertEqual(detail["reply_log"][0]["status"], "uncertain")
        with self.app.state.database.connection() as conn:
            saved_status = conn.execute(
                "SELECT status FROM replies WHERE id = 'reply-stale'"
            ).fetchone()["status"]
        self.assertEqual(saved_status, "uncertain")

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
            mailbox_uid="42",
        )

        class FakeMailbox:
            label = "imap/smtp"
            seen_uids: list[str] = []

            def fetch_messages(self) -> list[IncomingMail]:
                return [incoming]

            def mark_messages_seen(self, uids: list[str]) -> None:
                with sqlite3.connect(self_database_path) as probe:
                    self.assert_committed_count = probe.execute(
                        "SELECT COUNT(*) FROM emails WHERE id = ?",
                        (self_email_id,),
                    ).fetchone()[0]
                self.seen_uids.extend(uids)

            def send_message(self, **_: Any) -> str:
                return "unused"

        self_database_path = str(self.database_path)
        self_email_id = self.app.state.service._mail_email_id(incoming, "imap")
        mailbox = FakeMailbox()
        with patch.dict(os.environ, {"MAIL_PROVIDER": "imap"}, clear=False):
            app = create_app(self.database_path)
            with patch("backend.service.resolve_mail_provider", return_value=mailbox):
                status, _, first = request(app, "POST", "/api/mail/sync")
                self.assertEqual(status, 200)
                self.assertEqual(first["imported"], 1)
                self.assertEqual(first["threads"], 1)
                self.assertEqual(mailbox.assert_committed_count, 1)
                status, _, second = request(app, "POST", "/api/mail/sync")
                self.assertEqual(status, 200)
                self.assertEqual(second["imported"], 0)
                self.assertEqual(second["skipped"], 1)
                self.assertEqual(mailbox.seen_uids, ["42", "42"])

        thread_id = app.state.service._mail_thread_id(incoming)
        status, _, detail = request(app, "GET", f"/api/threads/{thread_id}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["thread"]["sender"], "Ada Lovelace")
        self.assertEqual(detail["emails"][0]["body"], incoming.body)
        self.assertEqual(detail["emails"][0]["attachments"][0]["filename"], "metrics.csv")
        self.assertEqual(detail["emails"][0]["attachments"][0]["size"], len(b"week,total\n1,42\n"))
        with app.state.database.connection() as conn:
            saved_message_id = conn.execute(
                "SELECT message_id FROM emails WHERE id = ?", (self_email_id,)
            ).fetchone()["message_id"]
        self.assertEqual(saved_message_id, incoming.message_key)

    def test_smtp_reply_includes_original_message_references(self) -> None:
        sent_messages: list[EmailMessage] = []

        class FakeSMTP:
            def __init__(self, *_: Any, **__: Any) -> None:
                pass

            def __enter__(self) -> "FakeSMTP":
                return self

            def __exit__(self, *_: Any) -> None:
                pass

            def login(self, *_: Any) -> None:
                pass

            def send_message(self, message: EmailMessage) -> None:
                sent_messages.append(message)

        with patch.dict(os.environ, {
            "MAIL_SMTP_HOST": "smtp.example.com",
            "MAIL_FROM": "me@example.com",
            "MAIL_USERNAME": "me@example.com",
            "MAIL_PASSWORD": "test-password",
        }, clear=False), patch("backend.providers.smtplib.SMTP_SSL", FakeSMTP):
            provider = IMAPSMTPMailProvider()
            provider.send_message(
                thread={
                    "reply_to_message_id": "<latest@example.com>",
                    "references": ["<root@example.com>", "<latest@example.com>"],
                },
                recipient="ada@example.com",
                subject="Re: Weekly metrics",
                body="Thanks for the details.",
            )
        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(sent_messages[0]["In-Reply-To"], "<latest@example.com>")
        self.assertEqual(sent_messages[0]["References"], "<root@example.com> <latest@example.com>")

    def test_existing_mail_database_gains_message_id_column(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as conn:
            conn.execute(
                """CREATE TABLE emails (
                    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, sender TEXT NOT NULL,
                    sender_email TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
                    received_at TEXT NOT NULL, direction TEXT NOT NULL,
                    do_not_reply INTEGER NOT NULL DEFAULT 0
                )"""
            )
        legacy_app = create_app(legacy_path)
        with legacy_app.state.database.connection() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(emails)")}
        self.assertIn("message_id", columns)

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

    def test_real_mail_parser_groups_root_and_replies_by_message_id(self) -> None:
        root = EmailMessage()
        root["Message-ID"] = "<root@example.com>"
        root["Subject"] = "Request: Weekly metrics"
        root.set_content("First message")
        reply = EmailMessage()
        reply["Message-ID"] = "<reply@example.com>"
        reply["References"] = "<root@example.com>"
        reply["In-Reply-To"] = "<root@example.com>"
        reply["Subject"] = "Re: Request: Weekly metrics"
        reply.set_content("A follow-up")

        root_mail = IMAPSMTPMailProvider._parse_message(root, "1")
        reply_mail = IMAPSMTPMailProvider._parse_message(reply, "2")
        self.assertEqual(root_mail.thread_key, "<root@example.com>")
        self.assertEqual(reply_mail.thread_key, root_mail.thread_key)
        self.assertEqual(
            self.app.state.service._mail_thread_id(root_mail),
            self.app.state.service._mail_thread_id(reply_mail),
        )

    def test_real_mailbox_blocks_demo_delivery_but_allows_explicit_real_reply(self) -> None:
        incoming = IncomingMail(
            message_key="<real-manual@example.com>",
            thread_key="<real-manual@example.com>",
            sender="Ada Lovelace",
            sender_email="ada@example.com",
            subject="Request: Weekly metrics",
            body="Please send the weekly metrics.",
            received_at="2026-09-14T04:00:00+00:00",
        )

        class RecordingMailbox:
            label = "imap/smtp"
            from_address = "owner@example.com"

            def __init__(self) -> None:
                self.sent: list[str] = []
                self.sent_thread: dict[str, Any] | None = None

            def fetch_messages(self) -> list[IncomingMail]:
                return [incoming]

            def send_message(self, *, thread: dict[str, Any], recipient: str, subject: str, body: str) -> str:
                self.sent.append(recipient)
                self.sent_thread = thread
                return "<recorded@example.com>"

        mailbox = RecordingMailbox()
        with patch.dict(os.environ, {"MAIL_PROVIDER": "imap"}, clear=False):
            app = create_app(self.database_path)
        with patch("backend.service.resolve_mail_provider", return_value=mailbox):
            status, _, blocked = request(app, "POST", "/api/threads/thread-customer-export/reply")
            self.assertEqual(status, 409)
            self.assertIn("Demo threads", blocked["detail"])
            self.assertEqual(mailbox.sent, [])

            status, _, synced = request(app, "POST", "/api/mail/sync")
            self.assertEqual(status, 200)
            self.assertEqual(synced["imported"], 1)
            thread_id = app.state.service._mail_thread_id(incoming)
            with app.state.database.transaction() as conn:
                row = conn.execute(
                    "SELECT state_json FROM requirements WHERE thread_id = ?", (thread_id,)
                ).fetchone()
                state = json.loads(row["state_json"])
                state["status"] = "ready"
                state["completeness"] = 100
                conn.execute(
                    "UPDATE requirements SET state_json = ?, status = 'ready', completeness = 100 WHERE thread_id = ?",
                    (json.dumps(state), thread_id),
                )
                conn.execute(
                    "UPDATE threads SET status = 'ready', completeness = 100 WHERE id = ?",
                    (thread_id,),
                )
            status, _, settings = request(app, "GET", "/api/settings")
            self.assertFalse(settings["auto_reply"])
            status, _, sent = request(
                app, "POST", f"/api/threads/{thread_id}/reply", {"body": "Confirmed weekly metrics."}
            )
            self.assertEqual(status, 200)
            self.assertEqual(mailbox.sent, ["ada@example.com"])
            self.assertEqual(mailbox.sent_thread["reply_to_message_id"], incoming.message_key)
            self.assertEqual(mailbox.sent_thread["references"], [incoming.message_key])
            self.assertEqual(sent["thread"]["status"], "replied")

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
