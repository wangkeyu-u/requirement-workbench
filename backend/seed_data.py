"""Deterministic, realistic mock mailbox data for the first-run demo."""

from __future__ import annotations

import io
import zipfile
from copy import deepcopy
from typing import Any

from .models import empty_requirement_state


def _minimal_pdf() -> bytes:
    """Build a tiny standards-shaped PDF with one readable page."""

    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    stream = b"BT /F1 12 Tf 24 64 Td (Requirement reference) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 240 120] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    result = bytearray(header)
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode("ascii"))
        result.extend(obj)
        result.extend(b"\nendobj\n")
    xref_offset = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    result.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(result)


def _minimal_xlsx() -> bytes:
    """Build a valid one-sheet XLSX using only the standard-library zip writer."""

    files = {
        "[Content_Types].xml": """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">
  <Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>
  <Default Extension=\"xml\" ContentType=\"application/xml\"/>
  <Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>
  <Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>
  <Override PartName=\"/docProps/core.xml\" ContentType=\"application/vnd.openxmlformats-package.core-properties+xml\"/>
  <Override PartName=\"/docProps/app.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.extended-properties+xml\"/>
</Types>""",
        "_rels/.rels": """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/>
  <Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties\" Target=\"docProps/core.xml\"/>
  <Relationship Id=\"rId3\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties\" Target=\"docProps/app.xml\"/>
</Relationships>""",
        "xl/workbook.xml": """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">
  <sheets><sheet name=\"Pilot\" sheetId=\"1\" r:id=\"rId1\"/></sheets>
</workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/>
</Relationships>""",
        "xl/worksheets/sheet1.xml": """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">
  <sheetData><row r=\"1\"><c r=\"A1\" t=\"inlineStr\"><is><t>Inventory pilot</t></is></c></row></sheetData>
</worksheet>""",
        "docProps/core.xml": """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" xmlns:dc=\"http://purl.org/dc/elements/1.1/\"><dc:title>Inventory pilot</dc:title></cp:coreProperties>""",
        "docProps/app.xml": """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Properties xmlns=\"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties\"><Application>Requirement Workbench</Application></Properties>""",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))
    return buffer.getvalue()


def _state(
    requirement_id: str,
    title: str,
    *,
    requester: str,
    category: str = "requirement",
    status: str = "waiting_for_me",
    completeness: int = 0,
    **values: Any,
) -> dict[str, Any]:
    state = empty_requirement_state(requirement_id, title)
    state.update({"requester": requester, "status": status, "completeness": completeness})
    state.update(values)
    return state


MOCK_THREADS: list[dict[str, Any]] = [
    {
        "id": "thread-performance-dashboard",
        "title": "Application performance dashboard",
        "sender": "Maya Chen",
        "sender_email": "maya.chen@example.com",
        "subject": "A dashboard for application performance",
        "category": "requirement",
        "status": "waiting_for_me",
        "question_count": 1,
        "unread_count": 1,
        "received_at": "2026-09-10T09:12:00+08:00",
        "requirement": _state(
            "req-performance-dashboard",
            "Application performance dashboard",
            requester="Maya Chen",
            completeness=48,
            background="Operations reviews production health across several services.",
            business_problem="Performance regressions are hard to spot across separate telemetry views.",
            goal="Monitor application performance from one operational dashboard.",
            stakeholders=["Platform Engineering"],
            scope=["A dashboard for production service performance trends"],
            functional_requirements=["Show service performance trends"],
            non_functional_requirements=["The dashboard should be useful in weekly operations reviews"],
            data_sources=["Production telemetry"],
            priority="High",
            open_questions=["这个仪表盘会由谁使用？"],
            risks=["The target audience and refresh expectation are not defined."],
        ),
        "question": {"field": "users", "text": "这个仪表盘会由谁使用？"},
        "emails": [
            {
                "id": "email-performance-dashboard-1",
                "sender": "Maya Chen",
                "sender_email": "maya.chen@example.com",
                "subject": "A dashboard for application performance",
                "body": (
                    "Hi team,\n\nWe need a dashboard to monitor application performance across our "
                    "production services. It should help us spot regressions and understand trends "
                    "during weekly operations reviews. I attached a reference PDF screenshot.\n\n"
                    "Thanks,\nMaya"
                ),
                "received_at": "2026-09-10T09:12:00+08:00",
                "direction": "inbound",
                "do_not_reply": False,
                "attachments": [
                    {
                        "id": "attachment-performance-reference",
                        "filename": "performance-dashboard-reference.pdf",
                        "content_type": "application/pdf",
                        "content": _minimal_pdf(),
                    }
                ],
            }
        ],
    },
    {
        "id": "thread-customer-export",
        "title": "Customer export workflow",
        "sender": "Jordan Lee",
        "sender_email": "jordan.lee@example.com",
        "subject": "Request: scheduled customer export",
        "category": "requirement",
        "status": "ready",
        "question_count": 0,
        "unread_count": 1,
        "received_at": "2026-09-10T08:45:00+08:00",
        "requirement": _state(
            "req-customer-export",
            "Customer export workflow",
            requester="Jordan Lee",
            status="ready",
            completeness=92,
            background="Finance operations needs a predictable way to deliver customer records.",
            business_problem="Manual exports are slow and create inconsistent files.",
            goal="Provide a scheduled CSV export of customer records.",
            stakeholders=["Finance Operations", "Customer Success"],
            users=["Finance Operations"],
            scope=["Schedule a CSV export", "Email a download link to approved recipients"],
            out_of_scope=["Changing customer data"],
            functional_requirements=[
                "Allow an approved user to choose a date range",
                "Generate a CSV with customer id, plan, and status",
                "Record each export in an audit log",
            ],
            non_functional_requirements=["Exports must be available within five minutes"],
            constraints=["Only approved recipients may receive the link"],
            dependencies=["Customer data service", "Notification service"],
            data_sources=["Customer database"],
            deadline="2026-10-15",
            priority="High",
            acceptance_criteria=[
                "An approved user can download the requested CSV",
                "An audit record is created for every export",
            ],
            assumptions=["CSV is sufficient for the first release"],
            risks=["Large date ranges may take longer than five minutes."],
        ),
        "question": None,
        "emails": [
            {
                "id": "email-customer-export-1",
                "sender": "Jordan Lee",
                "sender_email": "jordan.lee@example.com",
                "subject": "Request: scheduled customer export",
                "body": (
                    "Could we add a scheduled CSV export for Finance Operations? They need customer "
                    "id, plan, and status for a selected date range, with an audit log and a secure "
                    "download link. The first release is needed by 15 October 2026."
                ),
                "received_at": "2026-09-10T08:45:00+08:00",
                "direction": "inbound",
                "do_not_reply": False,
                "attachments": [],
            }
        ],
    },
    {
        "id": "thread-onboarding-refresh",
        "title": "New customer onboarding refresh",
        "sender": "Priya Nair",
        "sender_email": "priya.nair@example.com",
        "subject": "Can we refresh the onboarding flow?",
        "category": "requirement",
        "status": "waiting_for_me",
        "question_count": 1,
        "unread_count": 1,
        "received_at": "2026-09-09T16:05:00+08:00",
        "requirement": _state(
            "req-onboarding-refresh",
            "New customer onboarding refresh",
            requester="Priya Nair",
            completeness=35,
            background="New customers currently receive a long sequence of onboarding emails.",
            business_problem="The current onboarding experience has low activation after sign-up.",
            goal="Improve the new customer onboarding experience.",
            stakeholders=["Growth Marketing"],
            functional_requirements=["Review and simplify the onboarding email sequence"],
            data_sources=["Activation analytics"],
            open_questions=["这次改版要覆盖哪些客户群体？"],
            risks=["Success criteria are not yet specified."],
        ),
        "question": {
            "field": "scope",
            "text": "这次改版要覆盖哪些客户群体？",
        },
        "emails": [
            {
                "id": "email-onboarding-refresh-1",
                "sender": "Priya Nair",
                "sender_email": "priya.nair@example.com",
                "subject": "Can we refresh the onboarding flow?",
                "body": (
                    "The onboarding email sequence feels too long and activation is lower than we'd "
                    "like. Could we refresh the flow and simplify the first week of messages? We have "
                    "activation analytics available, but I am not sure whether we should start with all "
                    "customers or just the self-serve segment."
                ),
                "received_at": "2026-09-09T16:05:00+08:00",
                "direction": "inbound",
                "do_not_reply": False,
                "attachments": [],
            }
        ],
    },
    {
        "id": "thread-inventory-scanner",
        "title": "Warehouse inventory scanner pilot",
        "sender": "Sam Rivera",
        "sender_email": "sam.rivera@example.com",
        "subject": "FYI: inventory scanner pilot notes",
        "category": "requirement",
        "status": "do_not_reply",
        "do_not_reply": True,
        "question_count": 0,
        "unread_count": 0,
        "received_at": "2026-09-09T14:20:00+08:00",
        "requirement": _state(
            "req-inventory-scanner",
            "Warehouse inventory scanner pilot",
            requester="Sam Rivera",
            status="do_not_reply",
            completeness=61,
            background="The warehouse team is piloting handheld scanners for cycle counts.",
            business_problem="Manual counts take too long and create avoidable reconciliation work.",
            goal="Pilot a handheld workflow for faster inventory counts.",
            stakeholders=["Warehouse Operations"],
            users=["Warehouse associates"],
            scope=["Scan a shelf location", "Record counted quantity"],
            functional_requirements=["Allow offline capture while walking the warehouse"],
            constraints=["Pilot is limited to the East warehouse"],
            data_sources=["Inventory system"],
            risks=["Device connectivity may be inconsistent in some aisles."],
        ),
        "question": None,
        "emails": [
            {
                "id": "email-inventory-scanner-1",
                "sender": "Sam Rivera",
                "sender_email": "sam.rivera@example.com",
                "subject": "FYI: inventory scanner pilot notes",
                "body": (
                    "Sharing the inventory scanner pilot notes for awareness. The East warehouse is "
                    "testing offline shelf scans and quantity capture. Please do not reply to this "
                    "thread; I will send a follow-up when the pilot is complete."
                ),
                "received_at": "2026-09-09T14:20:00+08:00",
                "direction": "inbound",
                "do_not_reply": True,
                "attachments": [
                    {
                        "id": "attachment-inventory-notes",
                        "filename": "inventory-pilot-notes.xlsx",
                        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "content": _minimal_xlsx(),
                    }
                ],
            }
        ],
    },
    {
        "id": "thread-billing-anomaly",
        "title": "Monthly billing anomaly report",
        "sender": "Elena Garcia",
        "sender_email": "elena.garcia@example.com",
        "subject": "Automate the monthly billing anomaly report",
        "category": "requirement",
        "status": "ready",
        "question_count": 0,
        "unread_count": 1,
        "received_at": "2026-09-08T11:30:00+08:00",
        "requirement": _state(
            "req-billing-anomaly",
            "Monthly billing anomaly report",
            requester="Elena Garcia",
            status="ready",
            completeness=86,
            background="Finance reviews billing exceptions at the start of each month.",
            business_problem="The review is assembled manually from several billing exports.",
            goal="Automate a monthly report of billing anomalies.",
            stakeholders=["Finance", "Revenue Operations"],
            users=["Revenue Operations"],
            scope=["Detect unusual invoice totals", "Send a monthly summary"],
            out_of_scope=["Changing invoice records"],
            functional_requirements=["Flag anomalies against the trailing three-month baseline"],
            non_functional_requirements=["The report should be ready by 09:00 on the first business day"],
            constraints=["Use existing billing data"],
            dependencies=["Billing export job"],
            data_sources=["Billing ledger"],
            deadline="2026-11-01",
            priority="Medium",
            acceptance_criteria=["Finance can trace each flagged invoice to its source record"],
            risks=["Seasonal billing patterns may create false positives."],
        ),
        "question": None,
        "emails": [
            {
                "id": "email-billing-anomaly-1",
                "sender": "Elena Garcia",
                "sender_email": "elena.garcia@example.com",
                "subject": "Automate the monthly billing anomaly report",
                "body": (
                    "We would like to automate the monthly billing anomaly report. Please compare "
                    "invoice totals with the trailing three-month baseline, send Revenue Operations a "
                    "summary by 09:00 on the first business day, and keep a link back to each source "
                    "invoice. This should use the existing billing ledger."
                ),
                "received_at": "2026-09-08T11:30:00+08:00",
                "direction": "inbound",
                "do_not_reply": False,
                "attachments": [],
            }
        ],
    },
    {
        "id": "thread-product-newsletter",
        "title": "September product newsletter",
        "sender": "Product Updates",
        "sender_email": "updates@example.com",
        "subject": "September product newsletter",
        "category": "no_action",
        "status": "no_action",
        "question_count": 0,
        "unread_count": 0,
        "received_at": "2026-09-08T08:00:00+08:00",
        "requirement": _state(
            "req-product-newsletter",
            "September product newsletter",
            requester="Product Updates",
            category="no_action",
            status="no_action",
            completeness=0,
        ),
        "question": None,
        "emails": [
            {
                "id": "email-product-newsletter-1",
                "sender": "Product Updates",
                "sender_email": "updates@example.com",
                "subject": "September product newsletter",
                "body": (
                    "Here is the September product newsletter with release notes and community "
                    "stories. You are receiving this because you subscribed to product updates."
                ),
                "received_at": "2026-09-08T08:00:00+08:00",
                "direction": "inbound",
                "do_not_reply": False,
                "attachments": [],
            }
        ],
    },
    {
        "id": "thread-incident-routing",
        "title": "Incident alert routing",
        "sender": "Noah Williams",
        "sender_email": "noah.williams@example.com",
        "subject": "Route high-severity incidents to the on-call channel",
        "category": "requirement",
        "status": "waiting_for_me",
        "question_count": 1,
        "unread_count": 1,
        "received_at": "2026-09-07T17:40:00+08:00",
        "requirement": _state(
            "req-incident-routing",
            "Incident alert routing",
            requester="Noah Williams",
            completeness=63,
            background="On-call engineers currently watch several alert destinations.",
            business_problem="High-severity incidents can be missed when alerts arrive in separate channels.",
            goal="Route high-severity incidents to the on-call channel.",
            stakeholders=["Site Reliability Engineering"],
            users=["On-call engineers"],
            scope=["Route severity one and severity two incidents"],
            functional_requirements=["Send an alert to the on-call channel"],
            constraints=["Do not change existing paging rules"],
            data_sources=["Incident management service"],
            priority="High",
            open_questions=["如何确认告警已经成功路由？"],
            risks=["Duplicate alerts could create noise during an active incident."],
        ),
        "question": {
            "field": "acceptance_criteria",
            "text": "如何确认告警已经成功路由？",
        },
        "emails": [
            {
                "id": "email-incident-routing-1",
                "sender": "Noah Williams",
                "sender_email": "noah.williams@example.com",
                "subject": "Route high-severity incidents to the on-call channel",
                "body": (
                    "Can we route severity one and severity two incidents to the on-call channel? "
                    "Please keep the existing paging rules, and avoid sending duplicate alerts during "
                    "an active incident."
                ),
                "received_at": "2026-09-07T17:40:00+08:00",
                "direction": "inbound",
                "do_not_reply": False,
                "attachments": [],
            }
        ],
    },
    {
        "id": "thread-partner-portal",
        "title": "Partner portal access review",
        "sender": "Avery Thompson",
        "sender_email": "avery.thompson@example.com",
        "subject": "Partner portal access review",
        "category": "requirement",
        "status": "waiting_for_me",
        "question_count": 1,
        "unread_count": 1,
        "received_at": "2026-09-06T13:15:00+08:00",
        "requirement": _state(
            "req-partner-portal",
            "Partner portal access review",
            requester="Avery Thompson",
            completeness=43,
            background="Partners need a clearer view of their portal access and invitations.",
            business_problem="Access reviews are handled through spreadsheets and are difficult to audit.",
            goal="Make partner portal access review easier to audit.",
            stakeholders=["Partner Operations"],
            users=["Partner Operations"],
            functional_requirements=["List active partner invitations"],
            data_sources=["Identity service"],
            open_questions=["第一版除了审核，是否还要包含创建邀请？"],
            risks=["The requested scope may conflict with the existing invitation workflow."],
        ),
        "question": {
            "field": "scope",
            "text": "第一版除了审核，是否还要包含创建邀请？",
        },
        "emails": [
            {
                "id": "email-partner-portal-1",
                "sender": "Avery Thompson",
                "sender_email": "avery.thompson@example.com",
                "subject": "Partner portal access review",
                "body": (
                    "We need a simpler way for Partner Operations to review active portal access and "
                    "pending invitations. The spreadsheet process is hard to audit. One note: the last "
                    "proposal said to avoid changing the invitation workflow, but the latest ask may also "
                    "include creating invitations."
                ),
                "received_at": "2026-09-06T13:15:00+08:00",
                "direction": "inbound",
                "do_not_reply": False,
                "attachments": [],
            }
        ],
    },
    {
        "id": "thread-warehouse-realtime",
        "title": "Warehouse operations dashboard",
        "sender": "Liam Patel",
        "sender_email": "liam.patel@example.com",
        "subject": "A real-time dashboard for warehouse operations",
        "category": "requirement",
        "status": "waiting_for_me",
        "question_count": 1,
        "unread_count": 1,
        "received_at": "2026-09-05T10:50:00+08:00",
        "requirement": _state(
            "req-warehouse-realtime",
            "Warehouse operations dashboard",
            requester="Liam Patel",
            completeness=52,
            background="Warehouse leads need to see order throughput during the day.",
            business_problem="Current reports arrive too late to spot same-day bottlenecks.",
            goal="Give warehouse leads a real-time view of order throughput.",
            stakeholders=["Warehouse Operations"],
            users=["Warehouse leads"],
            scope=["Show orders received, picked, and shipped"],
            functional_requirements=["Display current order throughput"],
            data_sources=["Order management system"],
            priority="High",
            open_questions=["这里说的“实时”需要多长的刷新间隔？"],
            risks=["Real-time is ambiguous without a refresh interval."],
        ),
        "question": {"field": "functional_requirements", "text": "这里说的“实时”需要多长的刷新间隔？"},
        "emails": [
            {
                "id": "email-warehouse-realtime-1",
                "sender": "Liam Patel",
                "sender_email": "liam.patel@example.com",
                "subject": "A real-time dashboard for warehouse operations",
                "body": (
                    "Could we build a real-time dashboard for warehouse leads showing orders received, "
                    "picked, and shipped? The goal is to spot same-day bottlenecks. It should use the "
                    "order management system, but I have not defined what refresh interval real-time "
                    "should mean."
                ),
                "received_at": "2026-09-05T10:50:00+08:00",
                "direction": "inbound",
                "do_not_reply": False,
                "attachments": [],
            }
        ],
    },
    {
        "id": "thread-localization-request",
        "title": "Website localization request",
        "sender": "Sofia Rossi",
        "sender_email": "sofia.rossi@example.com",
        "subject": "Launch website localization for Italy",
        "category": "requirement",
        "status": "replied",
        "question_count": 0,
        "unread_count": 0,
        "received_at": "2026-09-04T15:00:00+08:00",
        "requirement": _state(
            "req-localization-request",
            "Website localization request",
            requester="Sofia Rossi",
            status="replied",
            completeness=88,
            background="The company is preparing an Italian market launch.",
            business_problem="Italian prospects currently see an English-only website.",
            goal="Launch an Italian version of the marketing website.",
            stakeholders=["Marketing", "Italy launch team"],
            users=["Italian prospects"],
            scope=["Translate public marketing pages", "Add an Italian language switcher"],
            out_of_scope=["Localizing the application product UI"],
            functional_requirements=["Allow visitors to switch between English and Italian"],
            non_functional_requirements=["Translated pages must preserve existing accessibility labels"],
            constraints=["Use the approved translation glossary"],
            dependencies=["Translation vendor"],
            data_sources=["CMS content"],
            deadline="2026-09-30",
            priority="Medium",
            acceptance_criteria=["All public launch pages are available in Italian"],
            assumptions=["The existing CMS supports locale variants"],
            risks=["Translation review time may affect the launch date."],
        ),
        "question": None,
        "replies": [
            {
                "id": "reply-localization-1",
                "body": (
                    "Hi Sofia,\n\nWe captured the Italian website localization requirement and its "
                    "30 September target. The scope currently covers public marketing pages and the "
                    "language switcher, not the product UI.\n\nBest,\nRequirement Workbench"
                ),
                "status": "sent",
                "created_at": "2026-09-04T16:10:00+08:00",
            }
        ],
        "emails": [
            {
                "id": "email-localization-request-1",
                "sender": "Sofia Rossi",
                "sender_email": "sofia.rossi@example.com",
                "subject": "Launch website localization for Italy",
                "body": (
                    "For the Italy launch, please localize the public marketing pages and add an "
                    "English/Italian switcher. The product UI is out of scope. We need the pages ready "
                    "by 30 September 2026 and will use the approved translation glossary."
                ),
                "received_at": "2026-09-04T15:00:00+08:00",
                "direction": "inbound",
                "do_not_reply": False,
                "attachments": [],
            },
            {
                "id": "email-localization-request-outbound-1",
                "sender": "Requirement Workbench",
                "sender_email": "me@localhost",
                "subject": "Re: Launch website localization for Italy",
                "body": (
                    "Hi Sofia,\n\nWe captured the Italian website localization requirement and its "
                    "30 September target. The scope currently covers public marketing pages and the "
                    "language switcher, not the product UI.\n\nBest,\nRequirement Workbench"
                ),
                "received_at": "2026-09-04T16:10:00+08:00",
                "direction": "outbound",
                "do_not_reply": False,
                "attachments": [],
            },
        ],
    },
]


def get_mock_threads() -> list[dict[str, Any]]:
    """Return a deep copy so tests or callers cannot mutate seed definitions."""

    return deepcopy(MOCK_THREADS)
