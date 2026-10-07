# Requirement Workbench architecture

The application converts email conversations into a reviewed requirement document.
The default environment uses a Mock mailbox and Mock model; optional providers use
IMAP/SMTP and DeepSeek. Provider configuration is backend-only.

## Components

| Location | Responsibility |
| --- | --- |
| `frontend/src/app/` | Next.js pages and the requirement workbench |
| `backend/app.py` | HTTP routes |
| `backend/service.py` | Analysis, clarification, reply gates and Markdown export |
| `backend/models.py` | Requirement schema and normalization |
| `backend/providers.py` | Model and mailbox providers |
| `backend/database.py` | SQLite transactions and persistence |
| `backend/tests/` | HTTP, state and provider-boundary regressions |

## Data flow

1. Mailbox sync stores messages and attachment metadata in SQLite.
2. Analysis sends the allowed email fields to the model provider and normalizes the
   requirement patch. Unknown fields stay empty.
3. The workbench presents the current clarification question and accepts an answer.
4. Requirement state and messages persist before the next step is displayed.
5. The reviewed requirement can be copied or downloaded as Markdown.

## Model input boundary

`_model_safe_email` projects sender, subject, body, time and direction. Attachments
contribute only filename, content type and size. Attachment bytes and internal mail
identifiers are excluded. The download API and the model input are separate paths.

## Reply authorization

`send_reply` enforces the following checks against stored settings and state;
thread-level blockers are centralized in `_reply_blocker`:

- Demo threads cannot be sent through a real mailbox.
- Thread-level and message-level DO NOT REPLY must both be clear.
- A pending clarification question blocks sending.
- The thread must belong to the requirement category.
- An existing `sending`, `uncertain` or `sent` reply prevents another send.
- The requirement must meet the configured completeness threshold.

The automatic path also checks AUTO REPLY. A manually requested reply does not
require that switch; it still passes the stored thread and completeness gates.

`send_reply` reserves a `sending` record in a transaction, releases the database lock
for the provider call, then marks the record `sent`. A provider error marks the
reservation `uncertain`. A stale `sending` reservation is also reconciled as
uncertain. The user must check the sent mailbox and resolve that state before a
retry. SMTP acceptance followed by failed local persistence still cannot establish
exactly-once email delivery.

## Verification

See [API contract](API_CONTRACT.md) and [dated validation](ACCEPTANCE.md).
[README](../README.md) contains setup and test commands. Mock tests do not establish
credential-validated DeepSeek or mailbox behavior.
