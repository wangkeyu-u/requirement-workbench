"""Pydantic models and requirement-state helpers for the HTTP contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


REQUIREMENT_LIST_FIELDS = frozenset({
    "stakeholders",
    "users",
    "scope",
    "out_of_scope",
    "functional_requirements",
    "non_functional_requirements",
    "constraints",
    "dependencies",
    "data_sources",
    "acceptance_criteria",
    "assumptions",
    "open_questions",
    "risks",
})

REQUIREMENT_FIELDS = (
    "title",
    "requester",
    "background",
    "business_problem",
    "goal",
    "stakeholders",
    "users",
    "scope",
    "out_of_scope",
    "functional_requirements",
    "non_functional_requirements",
    "constraints",
    "dependencies",
    "data_sources",
    "deadline",
    "priority",
    "acceptance_criteria",
    "assumptions",
    "open_questions",
    "risks",
    "status",
    "completeness",
)

# Fields a model may propose in an incremental patch. Identity and derived
# metadata are owned by the service/database and can never be model output.
REQUIREMENT_PATCH_FIELDS = frozenset(
    field for field in REQUIREMENT_FIELDS if field not in {"status", "completeness"}
)
REQUIREMENT_STRING_FIELDS = frozenset(
    {"title", "requester", "background", "business_problem", "goal"}
)
REQUIREMENT_NULLABLE_STRING_FIELDS = frozenset({"deadline", "priority"})
ANSWERABLE_REQUIREMENT_FIELDS = REQUIREMENT_PATCH_FIELDS

#: Completeness a requirement must reach before it counts as "ready" and before a
#: reply may be generated. Mirrored as a literal in
#: frontend/src/components/workbench/WorkbenchShell.tsx for the disabled-state hint.
REPLY_MIN_COMPLETENESS = 75


def empty_requirement_state(requirement_id: str, title: str = "") -> dict[str, Any]:
    """Return the complete, stable shape used by every requirement."""

    return {
        "id": requirement_id,
        "title": title,
        "requester": "",
        "background": "",
        "business_problem": "",
        "goal": "",
        "stakeholders": [],
        "users": [],
        "scope": [],
        "out_of_scope": [],
        "functional_requirements": [],
        "non_functional_requirements": [],
        "constraints": [],
        "dependencies": [],
        "data_sources": [],
        "deadline": None,
        "priority": None,
        "acceptance_criteria": [],
        "assumptions": [],
        "open_questions": [],
        "risks": [],
        "status": "waiting_for_me",
        "completeness": 0,
    }


def normalize_requirement_state(
    state: dict[str, Any] | None,
    requirement_id: str,
    title: str = "",
) -> dict[str, Any]:
    """Fill missing keys without inventing facts or changing known values."""

    normalized = empty_requirement_state(requirement_id, title)
    if state:
        normalized.update({key: value for key, value in state.items() if key in normalized})
    normalized["id"] = requirement_id
    if not normalized.get("title"):
        normalized["title"] = title
    for field in REQUIREMENT_LIST_FIELDS:
        value = normalized.get(field)
        if value is None:
            normalized[field] = []
        elif not isinstance(value, list):
            normalized[field] = [str(value)]
    normalized["completeness"] = int(normalized.get("completeness") or 0)
    return normalized


def is_filled(value: Any) -> bool:
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    return value is not None and bool(str(value).strip())


#: Relative importance of each requirement field when scoring completeness. These
#: are relative weights, not percentages, so the list can be edited without anyone
#: having to rebalance it back to a total of 100 by hand.
COMPLETENESS_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("background", 5),
    ("business_problem", 8),
    ("goal", 15),
    ("stakeholders", 8),
    ("users", 12),
    ("scope", 12),
    ("functional_requirements", 15),
    ("non_functional_requirements", 5),
    ("constraints", 5),
    ("dependencies", 3),
    ("data_sources", 5),
    ("deadline", 3),
    ("priority", 2),
    ("acceptance_criteria", 7),
)

COMPLETENESS_TOTAL_WEIGHT = sum(weight for _, weight in COMPLETENESS_WEIGHTS)


def calculate_completeness(state: dict[str, Any]) -> int:
    """Score how much of the weighted requirement signal is confirmed, 0-100.

    The weights are relative, not percentages, so the raw total is scaled by
    ``COMPLETENESS_TOTAL_WEIGHT``. Clamping the raw sum instead would silently
    discard the weight of the trailing fields: with a total of 105, a requirement
    could read 100% while ``dependencies`` and ``priority`` were still empty.
    """

    earned = sum(weight for field, weight in COMPLETENESS_WEIGHTS if is_filled(state.get(field)))
    return max(0, min(100, round(100 * earned / COMPLETENESS_TOTAL_WEIGHT)))


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    filename: str
    content_type: str
    size: int


class Email(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    thread_id: str
    sender: str
    sender_email: str
    subject: str
    body: str
    received_at: str
    direction: str = Field(pattern=r"^(inbound|outbound)$")
    do_not_reply: bool
    attachments: list[Attachment]


class Thread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    sender: str
    subject: str
    preview: str
    status: str
    completeness: int
    unread_count: int
    question_count: int
    updated_at: str
    do_not_reply: bool
    requirement_id: str
    category: str


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    text: str


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    body: str
    status: str
    created_at: str


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    requester: str
    background: str
    business_problem: str
    goal: str
    stakeholders: list[str]
    users: list[str]
    scope: list[str]
    out_of_scope: list[str]
    functional_requirements: list[str]
    non_functional_requirements: list[str]
    constraints: list[str]
    dependencies: list[str]
    data_sources: list[str]
    deadline: str | None
    priority: str | None
    acceptance_criteria: list[str]
    assumptions: list[str]
    open_questions: list[str]
    risks: list[str]
    status: str
    completeness: int


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str | None = Field(default=None, min_length=1)


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)


class DoNotReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    do_not_reply: bool


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_reply: bool


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_reply: bool
    llm_provider: str
    mail_provider: str


class ThreadDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread: Thread
    emails: list[Email]
    requirement: Requirement
    question: Question | None
    reply_log: list[Reply]


class MarkdownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown: str


class OkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
