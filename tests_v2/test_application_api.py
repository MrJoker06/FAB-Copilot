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
        case = await client.get("/api/v1/cases/CASE-1")
        chat = await client.post("/api/v1/chat", json={"message": "请概览当前工厂情况"})
        session_id = chat.json()["data"]["session_id"]
        session = await client.get(f"/api/v1/sessions/{session_id}")

    assert documents.json()["data"][0]["source"] == "CP-CVD-01"
    assert cases.json()["data"][0]["case_id"] == "CASE-1"
    assert case.json()["data"]["root_cause"] == "Chamber contamination"
    assert case.json()["data"]["solution"] == "Clean chamber"
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
    answer = response.json()["data"]["answer"]
    assert "Particle" in answer
    assert "8" in answer
    assert "get_defect_pareto" not in answer


@pytest.mark.asyncio
async def test_chat_answers_introduction_without_unrelated_tool_calls(tmp_path: Path) -> None:
    database_dir = tmp_path / "application"
    _create_application_databases(database_dir)
    gateway = RecordingGateway()
    app = create_app(
        APISettings(
            project_dir=tmp_path,
            application_database_dir=database_dir,
            model_api_key="",
        ),
        gateway,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"message": "介绍一下你自己"})

    assert response.status_code == 200
    assert gateway.calls == []
    assert response.json()["data"]["mode"] == "direct"
    assert "Fab Copilot" in response.json()["data"]["answer"]


@pytest.mark.asyncio
async def test_chat_returns_previewable_governed_knowledge_sources(tmp_path: Path) -> None:
    database_dir = tmp_path / "application"
    _create_application_databases(database_dir)
    gateway = RecordingGateway()
    app = create_app(APISettings(project_dir=tmp_path, application_database_dir=database_dir), gateway)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"message": "CVD 膜厚漂移的原因和处置建议"})
        session_id = response.json()["data"]["session_id"]
        session = await client.get(f"/api/v1/sessions/{session_id}")
        preview = await client.get("/api/v1/knowledge/chunks/1")

    assert response.status_code == 200
    assert gateway.calls == []
    assert response.json()["data"]["sources"][0]["reference_id"] == "KB-1"
    assert session.json()["data"]["messages"][1]["metadata"]["sources"][0]["chunk_id"] == 1
    assert preview.json()["data"]["chunks"][0]["content"] == "Thickness limits"


@pytest.mark.asyncio
async def test_model_configuration_api_supports_runtime_switch_without_exposing_key(tmp_path: Path) -> None:
    database_dir = tmp_path / "application"
    _create_application_databases(database_dir)
    app = create_app(
        APISettings(
            project_dir=tmp_path,
            application_database_dir=database_dir,
            model_api_key="environment-secret",
            admin_api_token="admin-secret",
        ),
        RecordingGateway(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        public = await client.get("/api/v1/settings/model/current")
        forbidden = await client.get("/api/v1/admin/settings/model")
        monitor_forbidden = await client.get("/api/v1/monitor/summary")
        headers = {"Authorization": "Bearer admin-secret"}
        initial = await client.get("/api/v1/admin/settings/model", headers=headers)
        monitor = await client.get("/api/v1/monitor/summary", headers=headers)
        updated = await client.post(
            "/api/v1/admin/settings/model",
            json={"model": "deepseek-v4-pro", "api_key": "runtime-secret"},
            headers=headers,
        )
        current = await client.get("/api/v1/admin/settings/model", headers=headers)

    assert public.status_code == 200
    assert public.json()["data"] == {"model": "deepseek-v4-flash"}
    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == "ADMIN_REQUIRED"
    assert monitor_forbidden.status_code == 403
    assert monitor.status_code == 200
    assert initial.status_code == 200
    assert initial.json()["data"]["api_key_source"] == "environment"
    assert updated.status_code == 200
    assert updated.json()["data"]["model"] == "deepseek-v4-pro"
    assert current.json()["data"]["api_key_source"] == "runtime"
    assert "runtime-secret" not in current.text


@pytest.mark.asyncio
async def test_archived_session_can_be_listed_restored_and_continued(tmp_path: Path) -> None:
    database_dir = tmp_path / "application"
    _create_application_databases(database_dir)
    app = create_app(
        APISettings(
            project_dir=tmp_path,
            application_database_dir=database_dir,
            model_api_key="",
        ),
        RecordingGateway(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/v1/sessions", json={"title": "待恢复会话"})
        session_id = created.json()["data"]["session_id"]
        await client.post(
            "/api/v1/chat",
            json={"message": "介绍一下你自己", "session_id": session_id},
        )
        await client.delete(f"/api/v1/sessions/{session_id}")
        archived = await client.get("/api/v1/sessions", params={"include_archived": True})
        await client.post(f"/api/v1/sessions/{session_id}/restore")
        continued = await client.post(
            "/api/v1/chat",
            json={"message": "你能做什么", "session_id": session_id},
        )
        detail = await client.get(f"/api/v1/sessions/{session_id}")

    archived_row = next(item for item in archived.json()["data"] if item["session_id"] == session_id)
    assert archived_row["archived_at"] is not None
    assert continued.status_code == 200
    assert detail.json()["data"]["archived_at"] is None
    assert len(detail.json()["data"]["messages"]) == 4
