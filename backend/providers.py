"""Provider interfaces plus deterministic Mock and optional DeepSeek adapters."""

from __future__ import annotations

import json
import hashlib
import html
import imaplib
import os
import re
import smtplib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.header import decode_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import getaddresses, make_msgid, parsedate_to_datetime
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from .models import (
    REPLY_MIN_COMPLETENESS,
    REQUIREMENT_FIELDS,
    REQUIREMENT_LIST_FIELDS,
    REQUIREMENT_NULLABLE_STRING_FIELDS,
    REQUIREMENT_PATCH_FIELDS,
    REQUIREMENT_STRING_FIELDS,
    calculate_completeness,
)
from .seed_data import get_mock_threads


class LLMProviderError(RuntimeError):
    """A configured LLM could not complete a request."""


class MailProviderError(RuntimeError):
    """A configured mailbox could not be read or used to send a message."""


@dataclass(frozen=True)
class QuestionSuggestion:
    field: str
    text: str


@dataclass(frozen=True)
class AnalysisResult:
    category: str
    patch: dict[str, Any]
    question: QuestionSuggestion | None


@dataclass(frozen=True)
class IncomingAttachment:
    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class IncomingMail:
    """A normalized inbound message returned by a real mailbox provider."""

    message_key: str
    thread_key: str
    sender: str
    sender_email: str
    subject: str
    body: str
    received_at: str
    attachments: tuple[IncomingAttachment, ...] = ()


def _invalid_llm_output(path: str, message: str) -> LLMProviderError:
    return LLMProviderError(f"Invalid LLM output at {path}: {message}")


def _require_exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing keys {missing}")
        if extra:
            details.append(f"unexpected keys {extra}")
        raise _invalid_llm_output(path, "; ".join(details) or "unexpected object shape")


def _validate_patch(patch: Any, path: str = "patch") -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise _invalid_llm_output(path, "must be an object")
    unknown = set(patch) - set(REQUIREMENT_PATCH_FIELDS)
    if unknown:
        raise _invalid_llm_output(path, f"unsupported fields {sorted(unknown)}")

    validated: dict[str, Any] = {}
    for field, value in patch.items():
        field_path = f"{path}.{field}"
        if field in REQUIREMENT_LIST_FIELDS:
            if not isinstance(value, list):
                raise _invalid_llm_output(field_path, "must be an array of strings")
            invalid_items = [index for index, item in enumerate(value) if not isinstance(item, str)]
            if invalid_items:
                raise _invalid_llm_output(
                    field_path,
                    f"array items at indexes {invalid_items} must be strings",
                )
            validated[field] = list(value)
        elif field in REQUIREMENT_NULLABLE_STRING_FIELDS:
            if value is not None and not isinstance(value, str):
                raise _invalid_llm_output(field_path, "must be a string or null")
            validated[field] = value
        elif field in REQUIREMENT_STRING_FIELDS:
            if not isinstance(value, str):
                raise _invalid_llm_output(field_path, "must be a string")
            validated[field] = value
        else:
            # REQUIREMENT_PATCH_FIELDS is intentionally exhaustive. Keep this
            # branch explicit so adding a new state field cannot silently make
            # unvalidated model data writable.
            raise _invalid_llm_output(field_path, "has no supported schema")
    return validated


def validate_question_payload(value: Any, path: str = "question") -> QuestionSuggestion | None:
    """Validate a nullable one-question response without coercing model data."""

    if value is None:
        return None
    if not isinstance(value, dict):
        raise _invalid_llm_output(path, "must be an object or null")
    _require_exact_keys(value, {"field", "text"}, path)
    field = value["field"]
    text = value["text"]
    if field is None and text is None:
        return None
    if not isinstance(field, str) or not field:
        raise _invalid_llm_output(f"{path}.field", "must be a non-empty string or null with text also null")
    if not isinstance(text, str) or not text.strip():
        raise _invalid_llm_output(f"{path}.text", "must be a non-empty string")
    if field not in REQUIREMENT_PATCH_FIELDS:
        raise _invalid_llm_output(
            f"{path}.field",
            f"must be a requirement field, not {field!r}",
        )
    return QuestionSuggestion(field=field, text=text)


def validate_question_result(value: Any) -> QuestionSuggestion | None:
    """Validate a provider's typed clarification result before persistence."""

    if value is None:
        return None
    if not isinstance(value, QuestionSuggestion):
        raise _invalid_llm_output("question", "provider returned an unexpected result type")
    return validate_question_payload({"field": value.field, "text": value.text})


def validate_analysis_payload(value: Any) -> AnalysisResult:
    """Parse the exact JSON contract expected from a configured LLM."""

    if not isinstance(value, dict):
        raise _invalid_llm_output("analysis", "must be an object")
    _require_exact_keys(value, {"category", "patch", "question"}, "analysis")
    category = value["category"]
    if not isinstance(category, str) or category not in {"requirement", "no_action"}:
        raise _invalid_llm_output("category", "must be exactly 'requirement' or 'no_action'")
    patch = _validate_patch(value["patch"])
    question = validate_question_payload(value["question"])
    if category == "no_action" and (patch or question is not None):
        raise _invalid_llm_output("analysis", "no_action cannot include a patch or question")
    return AnalysisResult(category=category, patch=patch, question=question)


def validate_analysis_result(value: AnalysisResult) -> AnalysisResult:
    """Validate provider results at the service boundary as well as JSON parsing."""

    if not isinstance(value, AnalysisResult):
        raise _invalid_llm_output("analysis", "provider returned an unexpected result type")
    question_payload: dict[str, Any] | None = None
    if value.question is not None:
        if not isinstance(value.question, QuestionSuggestion):
            raise _invalid_llm_output("question", "must be a QuestionSuggestion or null")
        question_payload = {"field": value.question.field, "text": value.question.text}
    question = validate_question_payload(question_payload)
    category = value.category
    if not isinstance(category, str) or category not in {"requirement", "no_action"}:
        raise _invalid_llm_output("category", "must be exactly 'requirement' or 'no_action'")
    patch = _validate_patch(value.patch)
    if category == "no_action" and (patch or question is not None):
        raise _invalid_llm_output("analysis", "no_action cannot include a patch or question")
    return AnalysisResult(category=category, patch=patch, question=question)


class LLMProvider(Protocol):
    label: str

    def analyze(
        self,
        thread: dict[str, Any],
        emails: list[dict[str, Any]],
        current_state: dict[str, Any],
    ) -> AnalysisResult: ...

    def suggest_question(
        self,
        thread: dict[str, Any],
        emails: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> QuestionSuggestion | None: ...

    def generate_reply(
        self,
        thread: dict[str, Any],
        emails: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> str: ...


class MailProvider(Protocol):
    label: str

    def fetch_messages(self) -> list[IncomingMail]: ...

    def send_message(
        self,
        *,
        thread: dict[str, Any],
        recipient: str,
        subject: str,
        body: str,
    ) -> str: ...


def _joined_body(emails: list[dict[str, Any]]) -> str:
    return "\n\n".join(str(email.get("body", "")) for email in emails)


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


class MockLLMProvider:
    """A transparent rules-based provider for a complete offline demo."""

    label = "mock"

    _question_order: tuple[tuple[str, str], ...] = (
        ("goal", "这条需求最主要的业务目标是什么？"),
        ("users", "谁会使用这个功能？"),
        ("scope", "第一版明确包含哪些范围？"),
        ("functional_requirements", "第一版需要实现哪些功能？"),
        ("data_sources", "需要使用哪些系统或数据来源？"),
        ("deadline", "有没有目标日期或截止时间？"),
        ("acceptance_criteria", "如何判断这条需求已经完成？"),
    )

    def __init__(self, label: str | None = None) -> None:
        if label:
            self.label = label

    def analyze(
        self,
        thread: dict[str, Any],
        emails: list[dict[str, Any]],
        current_state: dict[str, Any],
    ) -> AnalysisResult:
        text = _joined_body(emails).lower()
        if _contains_any(
            text,
            (
                "newsletter",
                "unsubscribe",
                "release notes",
                "community stories",
                "for awareness only",
            ),
        ) and not _contains_any(text, ("we need", "could we", "please build", "request:")):
            return AnalysisResult(category="no_action", patch={}, question=None)

        patch: dict[str, Any] = {}
        subject = str(thread.get("subject", ""))
        sender = str(thread.get("sender", ""))
        if not current_state.get("requester"):
            patch["requester"] = sender
        if not current_state.get("title"):
            patch["title"] = subject.removeprefix("Request:").strip() or subject

        if "dashboard" in text:
            if "performance" in text:
                patch.setdefault("goal", "Monitor application performance from one operational dashboard.")
                patch.setdefault("functional_requirements", ["Show service performance trends"])
                patch.setdefault("data_sources", ["Production telemetry"])
            elif "warehouse" in text or "throughput" in text:
                patch.setdefault("goal", "Give warehouse leads a real-time view of order throughput.")
                patch.setdefault("functional_requirements", ["Display current order throughput"])
                patch.setdefault("data_sources", ["Order management system"])
            else:
                patch.setdefault("goal", "Provide a dashboard for the requested operational metrics.")
        if "export" in text:
            patch.setdefault("goal", "Provide a predictable export of the requested records.")
            patch.setdefault("functional_requirements", ["Generate an export for an approved user"])
        if "onboarding" in text:
            patch.setdefault("goal", "Improve the new customer onboarding experience.")
            patch.setdefault("functional_requirements", ["Review and simplify the onboarding sequence"])
        if "scanner" in text or "inventory" in text:
            patch.setdefault("goal", "Pilot a handheld workflow for faster inventory counts.")
            patch.setdefault("functional_requirements", ["Record a scanned shelf quantity"])
        if "billing" in text or "invoice" in text:
            patch.setdefault("goal", "Automate a monthly report of billing anomalies.")
            patch.setdefault("functional_requirements", ["Flag unusual billing totals"])
        if "incident" in text or "alert" in text:
            patch.setdefault("goal", "Route high-severity incidents to the on-call channel.")
            patch.setdefault("functional_requirements", ["Send an alert to the on-call channel"])
        if "partner portal" in text or "invitation" in text:
            patch.setdefault("goal", "Make partner portal access review easier to audit.")
            patch.setdefault("functional_requirements", ["List active partner invitations"])
        if "locali" in text or "italian" in text:
            patch.setdefault("goal", "Launch an Italian version of the marketing website.")
            patch.setdefault("functional_requirements", ["Allow visitors to switch to Italian"])

        deadline_match = re.search(
            r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+20\d{2})\b",
            text,
        )
        if deadline_match and not current_state.get("deadline"):
            patch["deadline"] = deadline_match.group(1)

        provisional = dict(current_state)
        for field, value in patch.items():
            if field in REQUIREMENT_FIELDS:
                provisional[field] = value
        question = self.suggest_question(thread, emails, provisional)
        return AnalysisResult(category="requirement", patch=patch, question=question)

    def suggest_question(
        self,
        thread: dict[str, Any],
        emails: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> QuestionSuggestion | None:
        text = _joined_body(emails).lower()
        if state.get("status") == "no_action":
            return None
        if "real-time" in text or "realtime" in text:
            functional = [str(item).lower() for item in state.get("functional_requirements", [])]
            if not any(
                marker in item for item in functional for marker in ("refresh", "second", "minute", "hour")
            ):
                return QuestionSuggestion("functional_requirements", "这里说的“实时”需要多长的刷新间隔？")

        for field, prompt in self._question_order:
            if not state.get(field):
                return QuestionSuggestion(field, prompt)

        if calculate_completeness(state) < REPLY_MIN_COMPLETENESS:
            return QuestionSuggestion("acceptance_criteria", "如何判断这条需求已经完成？")
        return None

    def generate_reply(
        self,
        thread: dict[str, Any],
        emails: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> str:
        title = state.get("title") or thread.get("subject") or "your request"
        goal = state.get("goal") or "the requested outcome"
        scope = state.get("scope") or []
        lines = [
            f"Hi {thread.get('sender', 'there')},",
            "",
            f"Thanks for sharing the request for **{title}**. We captured the goal as: {goal}",
        ]
        if scope:
            lines.extend(["", "Current scope:", *[f"- {item}" for item in scope]])
        lines.extend(
            [
                "",
                "We will use this as the working requirement and keep the documented assumptions and open questions visible for review.",
                "",
                "Best,",
                "Requirement Workbench",
            ]
        )
        return "\n".join(lines)


class DeepSeekProvider:
    """Small JSON adapter; it never receives attachment bytes or attachment paths.

    A configured-but-failing DeepSeek raises ``LLMProviderError`` so the API can
    answer 502. It deliberately does not fall back to the mock provider, because a
    silent downgrade would present rule-based guesses as model output.
    """

    label = "deepseek"

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.last_error: str | None = None

    @staticmethod
    def _safe_context(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Copy only model-safe email fields. Attachment content is deliberately absent."""

        return [
            {
                "sender": email.get("sender"),
                "sender_email": email.get("sender_email"),
                "subject": email.get("subject"),
                "body": email.get("body"),
                "received_at": email.get("received_at"),
                "direction": email.get("direction"),
                "attachments": [
                    {
                        "filename": attachment.get("filename"),
                        "content_type": attachment.get("content_type"),
                        "size": attachment.get("size"),
                    }
                    for attachment in email.get("attachments", [])
                ],
            }
            for email in emails
        ]

    def _chat(self, instruction: str, payload: dict[str, Any]) -> Any:
        prompt = (
            "You are a cautious junior business analyst. Return JSON only. Never infer or quote "
            "attachment contents: attachments are metadata only and are excluded from analysis. "
            f"\n\n{instruction}\n\nContext:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        request_body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "Return valid JSON and do not invent unknown facts."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib_request.Request(
            f"{self.base_url}/chat/completions",
            data=request_body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=45) as response:
                decoded = json.loads(response.read().decode("utf-8"))
            content = decoded["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(str(part.get("text", "")) for part in content)
            content = str(content).strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
            # A clarification response may legitimately be JSON null. The
            # individual adapter method validates the shape it needs.
            return json.loads(content)
        except (urllib_error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            raise LLMProviderError(f"DeepSeek request failed: {exc}") from exc

    def analyze(
        self,
        thread: dict[str, Any],
        emails: list[dict[str, Any]],
        current_state: dict[str, Any],
    ) -> AnalysisResult:
        payload = {
            "thread": {key: thread.get(key) for key in ("id", "title", "subject", "sender")},
            "emails": self._safe_context(emails),
            "current_requirement": current_state,
        }
        raw = self._chat(
            "Classify as requirement or no_action and return {category, patch, question}. "
            "patch may contain only known requirement fields. question must be {field,text} "
            "or {field:null,text:null} when no clarification is needed. "
            "Write question.text in Simplified Chinese because it is shown in the application interface.",
            payload,
        )
        return validate_analysis_payload(raw)

    def suggest_question(
        self,
        thread: dict[str, Any],
        emails: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> QuestionSuggestion | None:
        payload = {
            "thread": {key: thread.get(key) for key in ("id", "title", "subject", "sender")},
            "emails": self._safe_context(emails),
            "requirement": state,
        }
        raw = self._chat(
            "Return the single most important missing clarification as {field,text}. "
            "Write the question in Simplified Chinese because it is shown in the application interface. "
            "When ready, return {field:null,text:null}. Do not update any requirement field.",
            payload,
        )
        return validate_question_payload(raw)

    def generate_reply(
        self,
        thread: dict[str, Any],
        emails: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> str:
        payload = {
            "thread": {key: thread.get(key) for key in ("id", "title", "subject", "sender")},
            "emails": self._safe_context(emails),
            "requirement": state,
        }
        raw = self._chat(
            "Generate a concise, factual reply body. Do not invent a deadline, scope, feasibility, "
            "cost, or commitment. Return {body}.",
            payload,
        )
        if not isinstance(raw, dict):
            raise _invalid_llm_output("reply", "must be an object")
        _require_exact_keys(raw, {"body"}, "reply")
        body = raw.get("body")
        if not isinstance(body, str) or not body.strip():
            raise _invalid_llm_output("reply.body", "must be a non-empty string")
        return body.strip()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise MailProviderError(f"{name} must be an integer") from exc


def _decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    chunks: list[str] = []
    for part, charset in decode_header(str(value)):
        if isinstance(part, bytes):
            chunks.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            chunks.append(part)
    return "".join(chunks).strip()


def _text_from_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</p\s*>", "\n\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _message_body(message: Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type().lower()
        if content_type == "text/plain":
            text = _text_from_part(part).strip()
            if text:
                plain_parts.append(text)
        elif content_type == "text/html":
            text = _html_to_text(_text_from_part(part))
            if text:
                html_parts.append(text)
    return "\n\n".join(plain_parts or html_parts).strip()


def _message_timestamp(message: Message) -> str:
    raw_date = message.get("Date")
    if raw_date:
        try:
            parsed = parsedate_to_datetime(raw_date)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
        except (TypeError, ValueError, OverflowError):
            pass
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _message_thread_key(subject: str, message: Message) -> str:
    references = str(message.get("References", ""))
    reference_ids = re.findall(r"<[^>]+>", references)
    if reference_ids:
        return reference_ids[0]
    in_reply_to = str(message.get("In-Reply-To", "")).strip()
    if in_reply_to:
        return in_reply_to
    normalized = re.sub(r"^(?:(?:re|fw|fwd):\s*)+", "", subject, flags=re.IGNORECASE).strip().lower()
    return f"subject:{normalized or 'untitled'}"


class IMAPSMTPMailProvider:
    """Generic IMAP inbox + SMTP sender for personal mailbox integrations.

    The provider intentionally uses the standard library so Gmail, Outlook, QQ,
    163 and other IMAP/SMTP services can be configured without adding vendor SDKs.
    It stores attachment bytes locally for download, while the service's model
    projection only exposes their filename, type and size to an LLM.
    """

    label = "imap/smtp"

    def __init__(self) -> None:
        self.imap_host = os.getenv("MAIL_IMAP_HOST", "").strip()
        self.imap_port = _env_int("MAIL_IMAP_PORT", 993 if _env_bool("MAIL_IMAP_SSL", True) else 143)
        self.imap_ssl = _env_bool("MAIL_IMAP_SSL", True)
        self.imap_folder = os.getenv("MAIL_IMAP_FOLDER", "INBOX").strip() or "INBOX"
        self.imap_search = os.getenv("MAIL_IMAP_SEARCH", "ALL").strip() or "ALL"
        self.imap_limit = max(1, _env_int("MAIL_IMAP_LIMIT", 50))
        self.imap_timeout = max(1, _env_int("MAIL_IMAP_TIMEOUT", 45))
        self.imap_mark_seen = _env_bool("MAIL_IMAP_MARK_SEEN", False)
        self.username = (os.getenv("MAIL_USERNAME") or os.getenv("MAIL_IMAP_USERNAME") or "").strip()
        self.password = os.getenv("MAIL_PASSWORD") or os.getenv("MAIL_IMAP_PASSWORD") or ""
        self.smtp_host = (os.getenv("MAIL_SMTP_HOST") or self.imap_host).strip()
        self.smtp_port = _env_int("MAIL_SMTP_PORT", 465 if _env_bool("MAIL_SMTP_SSL", True) else 587)
        self.smtp_ssl = _env_bool("MAIL_SMTP_SSL", True)
        self.smtp_starttls = _env_bool("MAIL_SMTP_STARTTLS", not self.smtp_ssl)
        self.from_address = (os.getenv("MAIL_FROM") or self.username).strip()

    def _check_imap_config(self) -> None:
        missing = [name for name, value in (("MAIL_IMAP_HOST", self.imap_host), ("MAIL_USERNAME", self.username), ("MAIL_PASSWORD", self.password)) if not value]
        if missing:
            raise MailProviderError(f"Mailbox configuration is incomplete: {', '.join(missing)}")

    def _check_smtp_config(self) -> None:
        missing = [name for name, value in (("MAIL_SMTP_HOST", self.smtp_host), ("MAIL_FROM", self.from_address), ("MAIL_USERNAME", self.username), ("MAIL_PASSWORD", self.password)) if not value]
        if missing:
            raise MailProviderError(f"SMTP configuration is incomplete: {', '.join(missing)}")

    def fetch_messages(self) -> list[IncomingMail]:
        self._check_imap_config()
        client: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None
        try:
            client = (
                imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=self.imap_timeout)
                if self.imap_ssl
                else imaplib.IMAP4(self.imap_host, self.imap_port, timeout=self.imap_timeout)
            )
            client.login(self.username, self.password)
            status, _ = client.select(self.imap_folder, readonly=not self.imap_mark_seen)
            if status != "OK":
                raise MailProviderError(f"Unable to open mailbox folder {self.imap_folder!r}")
            status, data = client.uid("search", None, self.imap_search)
            if status != "OK":
                raise MailProviderError(f"Mailbox search failed for {self.imap_search!r}")
            uids = (data[0] or b"").split() if data else []
            messages: list[IncomingMail] = []
            for raw_uid in uids[-self.imap_limit:]:
                status, fetched = client.uid("fetch", raw_uid, "(RFC822)")
                if status != "OK":
                    continue
                raw_message = next(
                    (item[1] for item in fetched if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes)),
                    None,
                )
                if raw_message is None:
                    continue
                message = BytesParser(policy=policy.default).parsebytes(raw_message)
                parsed = self._parse_message(message, raw_uid.decode("ascii", errors="replace"))
                messages.append(parsed)
                if self.imap_mark_seen:
                    client.uid("store", raw_uid, "+FLAGS", "\\Seen")
            return messages
        except MailProviderError:
            raise
        except (OSError, imaplib.IMAP4.error, UnicodeError, ValueError) as exc:
            raise MailProviderError(f"Mailbox sync failed: {exc}") from exc
        finally:
            if client is not None:
                try:
                    client.logout()
                except (OSError, imaplib.IMAP4.error):
                    pass

    @staticmethod
    def _parse_message(message: Message, uid: str) -> IncomingMail:
        subject = _decode_mime_header(message.get("Subject")) or "(no subject)"
        addresses = getaddresses([str(message.get("From", ""))])
        sender_name = _decode_mime_header(addresses[0][0]) if addresses else ""
        sender_email = addresses[0][1].strip() if addresses else ""
        sender = sender_name or sender_email or "Unknown sender"
        message_id = str(message.get("Message-ID", "")).strip() or f"uid:{uid}"
        attachments: list[IncomingAttachment] = []
        parts = message.walk() if message.is_multipart() else (message,)
        for part in parts:
            filename = _decode_mime_header(part.get_filename())
            if not filename:
                continue
            content = part.get_payload(decode=True) or b""
            attachments.append(
                IncomingAttachment(
                    filename=filename,
                    content_type=part.get_content_type() or "application/octet-stream",
                    content=content,
                )
            )
        return IncomingMail(
            message_key=message_id,
            thread_key=_message_thread_key(subject, message),
            sender=sender,
            sender_email=sender_email,
            subject=subject,
            body=_message_body(message),
            received_at=_message_timestamp(message),
            attachments=tuple(attachments),
        )

    def send_message(
        self,
        *,
        thread: dict[str, Any],
        recipient: str,
        subject: str,
        body: str,
    ) -> str:
        del thread
        self._check_smtp_config()
        message = EmailMessage(policy=policy.SMTP)
        message["From"] = self.from_address
        message["To"] = recipient
        message["Subject"] = subject
        message_id = make_msgid()
        message["Message-ID"] = message_id
        message.set_content(body)
        try:
            if self.smtp_ssl:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=45) as client:
                    client.login(self.username, self.password)
                    client.send_message(message)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=45) as client:
                    client.ehlo()
                    if self.smtp_starttls:
                        client.starttls()
                        client.ehlo()
                    client.login(self.username, self.password)
                    client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailProviderError(f"SMTP send failed: {exc}") from exc
        return message_id


class MockMailProvider:
    label = "mock"

    def fetch_messages(self) -> list[IncomingMail]:
        return []

    def send_message(
        self,
        *,
        thread: dict[str, Any],
        recipient: str,
        subject: str,
        body: str,
    ) -> str:
        # The database is the durable outbox for this demo; this id represents a mock delivery.
        return f"mock-message-{uuid.uuid4().hex}"

    @staticmethod
    def seed_threads() -> list[dict[str, Any]]:
        return get_mock_threads()


def configured_llm_label(configured: str, api_key: str | None = None) -> str:
    if api_key is None:
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    name = (configured or "mock").strip().lower()
    if name == "deepseek":
        return "deepseek" if api_key else "mock (DeepSeek key missing)"
    return "mock"


def resolve_llm_provider(configured: str) -> LLMProvider:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    name = (configured or "mock").strip().lower()
    if name == "deepseek" and api_key:
        return DeepSeekProvider(
            api_key=api_key,
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
    if name == "deepseek":
        # No key: say so in the provider label instead of pretending to be DeepSeek.
        return MockLLMProvider(label="mock (DeepSeek key missing)")
    return MockLLMProvider()


def resolve_mail_provider(configured: str) -> MailProvider:
    name = (configured or "mock").strip().lower()
    if name in {"imap", "imap_smtp", "gmail", "outlook", "qq", "163"}:
        return IMAPSMTPMailProvider()
    if name == "mock":
        return MockMailProvider()
    raise MailProviderError(f"Unsupported mail provider: {name}")


def configured_mail_label(configured: str) -> str:
    name = (configured or "mock").strip().lower() or "mock"
    if name in {"imap", "imap_smtp", "gmail", "outlook", "qq", "163"}:
        return "imap/smtp"
    if name != "mock":
        return f"未知邮箱服务 ({name})"
    return "mock"
