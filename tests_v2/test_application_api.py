from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from fab_api.app import create_app
from fab_api.settings import APISettings
from fab_contracts import IdentityContext, ToolResult


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any], identity: IdentityContext
    ) -> ToolResult:
        self.calls.append((tool_name, arguments, identity.user_id))
        values: dict[str, Any] = {
            "get_fab_overview": {
                "lots": 12,
                "yield_pct": 93.2,
                "avg_cycle_hours": 84.5,
                "excursions": 1,
            },
            "get_recent_excursions": [{"lot_id": "LOT-12", "excursion_code": "CVD-DRIFT"}],
            "get_defect_pareto": [{"defect_type": "Particle", "defect_count": 8}],
        }
        data = values[tool_name]
        return ToolResult(
            tool=tool_name,
            data=data,
            row_count=len(data) if isinstance(data, list) else 1,
            request_id=identity.request_id,
        )

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "status": "ready"}


def _create_application_databases(directory: Path) -> None:
    directory.mkdir()
    with sqlite3.connect(directory / "process_knowledge.db") as connection:
        connection.executescript(
            """
            CREATE TABLE knowledge_documents(
                title TEXT, source TEXT PRIMARY KEY, doc_type TEXT, version TEXT, status TEXT,
                effective_date TEXT, owner TEXT, authority TEXT, process_steps TEXT, tags TEXT
            );
            CREATE TABLE knowledge_chunks(
                chunk_id INTEGER PRIMARY KEY, title TEXT, source TEXT, section TEXT, content TEXT
            );
            CREATE TABLE historical_cases(
                case_id TEXT PRIMARY KEY, title TEXT, process_step TEXT, equipment_id TEXT,
                occurred_date TEXT, severity TEXT, problem TEXT, solution TEXT, result TEXT,
                summary TEXT, tags TEXT, equipment_family TEXT, defect_type TEXT, symptoms TEXT,
                root_cause TEXT, root_cause_confidence TEXT, validation_method TEXT,
                recurrence_status TEXT, approved_by TEXT, case_status TEXT
            );
            INSERT INTO knowledge_documents VALUES
                ('CVD Control Plan', 'CP-CVD-01', 'Control Plan', '2.1', 'Active',
                 '2026-01-01', 'Process Engineering', 'Controlled', 'CVD', 'thickness');
            INSERT INTO knowledge_chunks VALUES
                (1, 'CVD Control Plan', 'CP-CVD-01', 'Limits', 'Thickness limits');
            INSERT INTO historical_cases VALUES
                ('CASE-1', 'CVD drift', 'CVD', 'CVD-02', '2026-06-01', 'High', 'Drift',
                 'Clean chamber', 'Recovered', 'Chamber drift case', 'cvd', 'CVD family',
                 'Particle', 'High thickness', 'Chamber contamination', 'High', 'Split lot',
                 'No recurrence', 'QE', 'Validated');
            """
        )
    with sqlite3.connect(directory / "ai_operations.db") as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE chat_sessions(
                session_id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT,
                model TEXT, archived_at TEXT, last_message_preview TEXT
            );
            CREATE TABLE chat_messages(
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                role TEXT, content TEXT, metadata_json TEXT, client_message_id TEXT, created_at TEXT
            );
            """
        )


@pytest.mark.asyncio
async def test_application_routes_keep_knowledge_sessions_and_mcp_tools_separate(tmp_path: Path) -> None:
    database_dir = tmp_path / "application"
    _create_application_databases(database_dir)
    gateway = RecordingGateway()
    app = create_app(
        APISettings(project_dir=tmp_path, application_database_dir=database_dir),
        gateway,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        documents = await client.get("/api/v1/knowledge/documents")
        cases = await client.get("/api/v1/cases")
        chat = await client.post("/api/v1/chat", json={"message": "请概览当前工厂情况"})
        session_id = chat.json()["data"]["session_id"]
        session = await client.get(f"/api/v1/sessions/{session_id}")

    assert documents.json()["data"][0]["source"] == "CP-CVD-01"
    assert cases.json()["data"][0]["case_id"] == "CASE-1"
    assert [call[0] for call in gateway.calls] == ["get_fab_overview", "get_recent_excursions"]
    assert session.json()["data"]["messages"][0]["role"] == "user"
    assert session.json()["data"]["messages"][1]["metadata"]["mode"] == "deterministic-mcp"


@pytest.mark.asyncio
async def test_application_routes_enforce_dev_bearer_token(tmp_path: Path) -> None:
    database_dir = tmp_path / "application"
    _create_application_databases(database_dir)
    app = create_app(
        APISettings(
            project_dir=tmp_path,
            application_database_dir=database_dir,
            dev_api_token="secret-token",
        ),
        RecordingGateway(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rejected = await client.get("/api/v1/sessions")
        accepted = await client.get("/api/v1/sessions", headers={"Authorization": "Bearer secret-token"})
    assert rejected.status_code == 401
    assert rejected.json()["error_code"] == "AUTHENTICATION_REQUIRED"
    assert accepted.status_code == 200


@pytest.mark.asyncio
async def test_chat_router_selects_specialized_defect_tool(tmp_path: Path) -> None:
    database_dir = tmp_path / "application"
    _create_application_databases(database_dir)
    gateway = RecordingGateway()
    app = create_app(APISettings(project_dir=tmp_path, application_database_dir=database_dir), gateway)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"message": "查看近期缺陷 Pareto"})
    assert response.status_code == 200
    assert gateway.calls[0][0] == "get_defect_pareto"
    assert "get_defect_pareto" in response.json()["data"]["answer"]
