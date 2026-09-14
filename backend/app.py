"""FastAPI application for the Requirement Workbench MVP."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .database import Database
from .models import (
    AnswerRequest,
    DoNotReplyRequest,
    MarkdownResponse,
    OkResponse,
    ReplyRequest,
    Settings,
    SettingsPatch,
    Thread,
    ThreadDetail,
)
from .service import WorkbenchService


def _local_frontend_origins() -> list[str]:
    """Allow only local browser origins used by the configured dev port."""

    ports = {3000, 3001}
    for value in os.getenv("FRONTEND_PORT", "").split(","):
        value = value.strip()
        if value.isdigit() and 1 <= int(value) <= 65535:
            ports.add(int(value))

    origins: list[str] = []
    for port in sorted(ports):
        origins.extend((f"http://localhost:{port}", f"http://127.0.0.1:{port}"))
    return origins


def create_app(database_path: str | Path | None = None) -> FastAPI:
    database = Database(database_path)
    database.initialize()
    service = WorkbenchService(database)
    app = FastAPI(title="Requirement Workbench API", version="0.1.0")
    app.state.database = database
    app.state.service = service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_local_frontend_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/threads", response_model=list[Thread])
    def list_threads() -> list[dict]:
        return service.list_threads()

    @app.post("/api/mail/sync")
    def sync_mailbox() -> dict[str, object]:
        return service.sync_mailbox()

    @app.get("/api/threads/{thread_id}", response_model=ThreadDetail)
    def get_thread(thread_id: str) -> dict:
        return service.detail(thread_id)

    @app.post("/api/threads/{thread_id}/analyze", response_model=ThreadDetail)
    def analyze_thread(thread_id: str) -> dict:
        return service.analyze(thread_id)

    @app.post("/api/threads/{thread_id}/answer", response_model=ThreadDetail)
    def answer_thread(thread_id: str, payload: AnswerRequest) -> dict:
        return service.answer(thread_id, payload.answer)

    @app.patch("/api/threads/{thread_id}", response_model=ThreadDetail)
    def patch_thread(thread_id: str, payload: DoNotReplyRequest) -> dict:
        return service.update_thread_do_not_reply(thread_id, payload.do_not_reply)

    @app.patch("/api/emails/{email_id}", response_model=OkResponse)
    def patch_email(email_id: str, payload: DoNotReplyRequest) -> dict[str, bool]:
        return service.update_email_do_not_reply(email_id, payload.do_not_reply)

    @app.get("/api/settings", response_model=Settings)
    def get_settings() -> dict:
        return service.settings()

    @app.patch("/api/settings", response_model=Settings)
    def patch_settings(payload: SettingsPatch) -> dict:
        return service.update_settings(payload.auto_reply)

    @app.post("/api/threads/{thread_id}/reply", response_model=ThreadDetail)
    def reply_thread(thread_id: str, payload: ReplyRequest | None = None) -> dict:
        return service.send_reply(thread_id, payload.body if payload else None)

    @app.get("/api/requirements/{requirement_id}/markdown", response_model=MarkdownResponse)
    def get_requirement_markdown(requirement_id: str) -> dict[str, str]:
        return {"markdown": service.requirement_markdown(requirement_id)}

    @app.get("/api/attachments/{attachment_id}")
    def get_attachment(attachment_id: str, download: bool = Query(default=False)) -> Response:
        metadata, content = service.attachment(attachment_id)
        headers = {}
        if download:
            headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(metadata['filename'])}"
        else:
            headers["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(metadata['filename'])}"
        return Response(content=content, media_type=metadata["content_type"], headers=headers)

    return app


app = create_app()
