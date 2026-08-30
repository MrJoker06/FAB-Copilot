"""Serve the current source against disposable SQLite snapshots for browser tests."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import closing, suppress
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, build_opener


PROJECT_DIR = Path(__file__).resolve().parents[1]
REFERENCE_DEPARTMENTS = PROJECT_DIR / "data" / "departments"
DEPARTMENT_DATABASES = {
    "FAB_MANUFACTURING_DATABASE_PATH": "manufacturing_operations.db",
    "FAB_EQUIPMENT_DATABASE_PATH": "equipment_engineering.db",
    "FAB_QUALITY_DATABASE_PATH": "yield_quality.db",
    "FAB_KNOWLEDGE_DATABASE_PATH": "process_knowledge.db",
    "FAB_AGENT_DATABASE_PATH": "ai_operations.db",
}
BROWSER_TEST_ADMIN_TOKEN = "browser-test-admin-token"
BROWSER_TEST_FIXTURE_KEY = "browser-test-fixture-key"
DEFAULT_PORT = 8899
BROWSER_TEST_MODEL_CAPABILITIES = {
    "deepseekv4-flash": {"streaming": True, "tool_calls": True, "thinking": False, "native_multimodal": False},
    "deepseekv4-pro": {"streaming": True, "tool_calls": True, "thinking": True, "native_multimodal": False},
}
BROWSER_TEST_VISUAL_TENANT_ID = "browser-test"
BROWSER_TEST_VISUAL_USER_ID = "browser-test-user"
BROWSER_TEST_VISUAL_SESSION_ID = "ux015-visual-session"
BROWSER_TEST_VISUAL_DOCUMENT_ID = "ux015-visual-document"
BROWSER_TEST_VISUAL_CHUNK_ID = "ux015-visual-chunk-0001"
BROWSER_TEST_VISUAL_TIMESTAMP = "2026-08-19T09:30:00+00:00"
BROWSER_TEST_VISUAL_DOCUMENT_FILENAME = (
    "2026-Q3-CMP-Polishing-超长文件名-多语言术语-"
    "wafer-surface-defect-SPC-control-plan-设备维护与异常处置指南-v1.0.txt"
)
BROWSER_TEST_VISUAL_DOCUMENT_TITLE = "CMP 抛光表面缺陷 SPC 控制计划与设备维护指南"
BROWSER_TEST_VISUAL_DOCUMENT_CONTENT = """# CMP 抛光异常处置 / CMP polishing response

当 wafer surface defect、particle 与 scratch 指标连续偏离控制线时，先核对 CMP-02 的 slurry flow、pad conditioning 和 endpoint trace。

## 固定检查清单

1. 对比 SPC control chart 与最近三批 lot 的 removal rate。
2. 检查 polishing pad 使用寿命、conditioning disk 和 filter differential pressure。
3. 记录工程师复核结论，并在 shift handoff 中同步中英文术语。
"""
BROWSER_TEST_VISUAL_ASSISTANT_ANSWER = """# CVD-02 膜厚漂移复核建议

## 结论

当前批次的 **thickness trend** 显示轻微上移，但尚不足以单独判定为制程失控。建议把 CVD-02 的 chamber A 与 chamber B 分开复核，并以 SPC 控制图、recipe revision 和 wafer map 作为同一时间窗内的证据。

## 建议的工程动作

1. **确认数据窗口**：按 lot、recipe、chamber 分组，对比近三周 deposition rate、uniformity 和 particle count；不要把 maintenance 后的首批 wafer 与稳定批次直接混合。
2. **核对设备状态**：检查 MFC、RF power、temperature controller 与 pressure trace；若出现 alarm 或 preventive maintenance，记录其开始和结束时间。
3. **复核统计边界**：对每个 chamber 分别计算 mean、sigma、Cp/Cpk，并将异常点回溯到工艺变更、gas line purge 或 fixture 更换。
4. **安排验证**：在下一次 engineering run 前固定 monitor wafer，并同步量测 recipe、椭偏仪校准状态和 shift handoff 内容。

> 风险提示：若膜厚偏移与颗粒数同时上升，应优先排查 chamber clean、showerhead 和 gas delivery；若只有单腔偏移，则先限制该 chamber 的高风险产品。

### 交接模板

| 项目 | 需要记录的证据 |
| --- | --- |
| CVD-02 / chamber | lot、recipe、maintenance 状态 |
| Thickness | target、mean、3σ、wafer map 摘要 |
| SPC | rule violation、行动负责人、完成时间 |

请在工程评审前保留原始 trend、设备 trace 和复核签名，避免仅依据单一平均值做结论。"""
DIRECT_LOOPBACK_PROXY_HANDLER = ProxyHandler({})
DIRECT_LOOPBACK_OPENER = build_opener(DIRECT_LOOPBACK_PROXY_HANDLER)

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


def backup_database(source: Path, destination: Path) -> None:
    """Copy an existing SQLite database through a read-only connection."""
    if not source.is_file():
        raise FileNotFoundError(f"browser test reference database is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as reader, closing(sqlite3.connect(destination)) as writer:
        reader.backup(writer)


def prepare_browser_test_model_capabilities(database_path: Path) -> None:
    """Make the disposable model catalog exercise both Thinking capability states."""
    expected_models = tuple(BROWSER_TEST_MODEL_CAPABILITIES)
    with closing(sqlite3.connect(database_path)) as connection:
        rows = connection.execute(
            f"SELECT model_id FROM model_catalog WHERE model_id IN ({','.join('?' for _ in expected_models)})",
            expected_models,
        ).fetchall()
        present_models = {row[0] for row in rows}
        missing_models = [model_id for model_id in expected_models if model_id not in present_models]
        if missing_models:
            raise RuntimeError(
                "browser test model capability fixture requires published catalog models: "
                + ", ".join(missing_models)
            )
        connection.executemany(
            "UPDATE model_catalog SET capabilities_json = ? WHERE model_id = ?",
            [
                (json.dumps(capabilities, separators=(",", ":")), model_id)
                for model_id, capabilities in BROWSER_TEST_MODEL_CAPABILITIES.items()
            ],
        )
        connection.commit()


def prepare_browser_test_visual_fixtures(agent_database_path: Path, knowledge_database_path: Path) -> None:
    """Seed deterministic UX-015 content only into disposable browser-test snapshots."""
    with closing(sqlite3.connect(agent_database_path)) as connection:
        connection.execute(
            """INSERT OR REPLACE INTO chat_sessions(
                   session_id, tenant_id, owner_user_id, title, created_at, updated_at, model, last_message_preview
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                BROWSER_TEST_VISUAL_SESSION_ID, BROWSER_TEST_VISUAL_TENANT_ID, BROWSER_TEST_VISUAL_USER_ID,
                "CVD-02 膜厚漂移复核", BROWSER_TEST_VISUAL_TIMESTAMP, BROWSER_TEST_VISUAL_TIMESTAMP,
                "deepseekv4-pro", "请复核 CVD-02 的膜厚漂移与 SPC 风险。",
            ),
        )
        connection.execute("DELETE FROM chat_messages WHERE session_id = ?", (BROWSER_TEST_VISUAL_SESSION_ID,))
        connection.executemany(
            """INSERT INTO chat_messages(session_id, role, content, metadata_json, client_message_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (BROWSER_TEST_VISUAL_SESSION_ID, "user", "请复核 CVD-02 的膜厚漂移与 SPC 风险。", "{}", "ux015-user-message", BROWSER_TEST_VISUAL_TIMESTAMP),
                (BROWSER_TEST_VISUAL_SESSION_ID, "assistant", BROWSER_TEST_VISUAL_ASSISTANT_ANSWER, "{}", None, BROWSER_TEST_VISUAL_TIMESTAMP),
            ],
        )
        connection.commit()
    with closing(sqlite3.connect(knowledge_database_path)) as connection:
        connection.execute("DELETE FROM personal_knowledge_fts WHERE document_id = ?", (BROWSER_TEST_VISUAL_DOCUMENT_ID,))
        connection.execute("DELETE FROM personal_knowledge_chunks WHERE document_id = ?", (BROWSER_TEST_VISUAL_DOCUMENT_ID,))
        connection.execute("DELETE FROM personal_knowledge_jobs WHERE document_id = ?", (BROWSER_TEST_VISUAL_DOCUMENT_ID,))
        connection.execute("DELETE FROM personal_knowledge_documents WHERE document_id = ?", (BROWSER_TEST_VISUAL_DOCUMENT_ID,))
        connection.execute(
            """INSERT INTO personal_knowledge_documents(
                   document_id, owner_user_id, filename, title, mime_type, size_bytes, checksum_sha256,
                   process_steps_json, equipment_ids_json, effective_date, tags_json, tags_source, status,
                   storage_key, parser_version, idempotency_key, created_at, updated_at
               ) VALUES (?, ?, ?, ?, 'text/plain', ?, ?, ?, ?, ?, ?, 'user', 'ready', ?, ?, ?, ?, ?)""",
            (
                BROWSER_TEST_VISUAL_DOCUMENT_ID, BROWSER_TEST_VISUAL_USER_ID, BROWSER_TEST_VISUAL_DOCUMENT_FILENAME,
                BROWSER_TEST_VISUAL_DOCUMENT_TITLE, len(BROWSER_TEST_VISUAL_DOCUMENT_CONTENT.encode("utf-8")),
                "ux015-visual-checksum", '["CMP"]', '["CMP-02"]', "2026-08-19", '["SPC", "多语言"]',
                "ux015/visual/original.txt", "browser-test-v1", "ux015-visual-idempotency",
                BROWSER_TEST_VISUAL_TIMESTAMP, BROWSER_TEST_VISUAL_TIMESTAMP,
            ),
        )
        connection.execute(
            """INSERT INTO personal_knowledge_chunks(
                   chunk_id, document_id, owner_user_id, page_number, section_path, chunk_index, content, token_count, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (BROWSER_TEST_VISUAL_CHUNK_ID, BROWSER_TEST_VISUAL_DOCUMENT_ID, BROWSER_TEST_VISUAL_USER_ID, 1,
             "CMP 抛光异常处置", 0, BROWSER_TEST_VISUAL_DOCUMENT_CONTENT, 92, BROWSER_TEST_VISUAL_TIMESTAMP),
        )
        connection.execute(
            """INSERT INTO personal_knowledge_jobs(
                   job_id, document_id, owner_user_id, status, stage, progress, attempt, created_at, updated_at
               ) VALUES (?, ?, ?, 'ready', 'complete', 100, 1, ?, ?)""",
            ("ux015-visual-job", BROWSER_TEST_VISUAL_DOCUMENT_ID, BROWSER_TEST_VISUAL_USER_ID,
             BROWSER_TEST_VISUAL_TIMESTAMP, BROWSER_TEST_VISUAL_TIMESTAMP),
        )
        connection.execute(
            """INSERT INTO personal_knowledge_fts(title, section_path, content, owner_user_id, document_id, chunk_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (BROWSER_TEST_VISUAL_DOCUMENT_TITLE, "CMP 抛光异常处置", BROWSER_TEST_VISUAL_DOCUMENT_CONTENT,
             BROWSER_TEST_VISUAL_USER_ID, BROWSER_TEST_VISUAL_DOCUMENT_ID, BROWSER_TEST_VISUAL_CHUNK_ID),
        )
        connection.commit()


def browser_test_environment(root: Path, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Return deterministic isolated settings without inherited application state."""
    environment = dict(os.environ if environ is None else environ)
    for key in list(environment):
        if key.startswith(("FAB_", "DEEPSEEK_", "AGENT_")):
            environment.pop(key, None)
    departments = root / "departments"
    snapshots = {key: departments / filename for key, filename in DEPARTMENT_DATABASES.items()}
    for destination in snapshots.values():
        backup_database(REFERENCE_DEPARTMENTS / destination.name, destination)
    prepare_browser_test_model_capabilities(snapshots["FAB_AGENT_DATABASE_PATH"])
    prepare_browser_test_visual_fixtures(
        snapshots["FAB_AGENT_DATABASE_PATH"], snapshots["FAB_KNOWLEDGE_DATABASE_PATH"]
    )
    environment.update({
        "FAB_DATABASE_DIR": str(departments),
        "FAB_DATABASE_PATH": str(root / "legacy.db"),
        **{key: str(value) for key, value in snapshots.items()},
        "FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH": str(root / "personal_knowledge"),
        "AGENT_LOG_PATH": str(root / "agent_events.jsonl"),
        "AGENT_RUN_LOG_DIR": str(root / "agent_runs"),
        "FAB_INSTANCE_ID": "playwright-browser-test",
        "FAB_INSTANCE_ROOT": str(root),
        "FAB_SOURCE_ROOT": str(PROJECT_DIR),
        "FAB_WORKSPACE_ENV_FILE": str(root / "missing-workspace.env"),
        "FAB_PROJECT_ENV_FILE": str(root / "missing-project.env"),
        "FAB_ADMIN_API_TOKEN": BROWSER_TEST_ADMIN_TOKEN,
        "FAB_REQUIRE_IDENTITY": "false",
        "FAB_ENTERPRISE_MODE": "true",
        "FAB_DATA_PROVIDER": "synthetic",
        "FAB_DEFAULT_TENANT_ID": "browser-test",
        "FAB_DEFAULT_USER_ID": "browser-test-user",
        "FAB_MOCK_SEED": "20260812",
        "FAB_MODEL_PROVIDER": "browser-test",
        "FAB_MODEL_NAME": "browser-test-model",
        "FAB_MODEL_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "FAB_MODEL_BASE_URL": "http://127.0.0.1:9",
        "DEEPSEEK_BASE_URL": "http://127.0.0.1:9",
        "AGENT_LOG_CONTENT": "metadata",
    })
    return environment


def parse_port(value: str) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def compatibility_fixture_port(app_port: int) -> int:
    """Reserve the adjacent loopback port without wrapping beyond TCP bounds."""
    if app_port >= 65535:
        raise ValueError("browser-test app port must leave room for the compatibility fixture")
    return app_port + 1


def scan_browser_test_artifacts(root: Path) -> None:
    """Fail closed if the server-only deterministic fixture key reaches disk."""
    needle = BROWSER_TEST_FIXTURE_KEY.encode()
    for path in root.rglob("*"):
        if path.is_file() and needle in path.read_bytes():
            raise RuntimeError("browser-test fixture key leaked into isolated artifacts")


def install_browser_test_compatibility_key() -> None:
    """Inject the dummy key only into the disposable server's probe connection."""
    import app.main as main
    from app.config import ModelConnection
    original = main.check_model_compatibility

    async def probe(connection, capabilities, **kwargs):
        fixture_connection = ModelConnection(connection.provider, BROWSER_TEST_FIXTURE_KEY, connection.base_url, connection.model)
        return await original(fixture_connection, capabilities, **kwargs)

    main.check_model_compatibility = probe


def stage_message(stage: str, **fields: str | int) -> str:
    """Format concise lifecycle diagnostics consumed by local Playwright runs."""
    if stage not in {"snapshot-preparation", "port-start", "health-ready", "health-failed"}:
        raise ValueError(f"unsupported browser-test stage: {stage}")
    suffix = " ".join(f"{key}={value}" for key, value in fields.items())
    return f"browser-test stage={stage}" + (f" {suffix}" if suffix else "")


def wait_for_loopback_health(
    url: str,
    *,
    timeout_seconds: float = 5.0,
    interval_seconds: float = 0.1,
    opener=None,
    sleeper=time.sleep,
    clock=time.monotonic,
) -> bool:
    """Poll the test app's loopback health route for a bounded post-start diagnostic."""
    parsed = urlparse(url)
    if parsed.hostname != "127.0.0.1" or parsed.path != "/api/health":
        raise ValueError("browser-test health URL must be the loopback /api/health route")
    request_opener = DIRECT_LOOPBACK_OPENER.open if opener is None else opener
    deadline = clock() + timeout_seconds
    while True:
        try:
            with closing(request_opener(url, timeout=min(1.0, max(0.1, deadline - clock())))) as response:
                if response.status == 200:
                    return True
        except (HTTPError, OSError):
            pass
        if clock() >= deadline:
            return False
        sleeper(min(interval_seconds, max(0.0, deadline - clock())))


async def report_health_after_start(url: str) -> None:
    ready = await asyncio.to_thread(wait_for_loopback_health, url)
    stage = "health-ready" if ready else "health-failed"
    print(stage_message(stage, url=url), flush=True)


def run_server(port: int) -> None:
    """Run uvicorn and report a bounded real loopback health probe."""
    import uvicorn

    class ReadyReportingServer(uvicorn.Server):
        _health_task: asyncio.Task[None] | None = None

        async def startup(self, sockets=None):  # type: ignore[no-untyped-def]
            await super().startup(sockets=sockets)
            if self.started:
                self._health_task = asyncio.create_task(
                    report_health_after_start(f"http://127.0.0.1:{port}/api/health")
                )

        async def shutdown(self, sockets=None):  # type: ignore[no-untyped-def]
            if self._health_task and not self._health_task.done():
                self._health_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._health_task
            await super().shutdown(sockets=sockets)

    configuration = uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="warning")
    ReadyReportingServer(configuration).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=parse_port, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    temporary = Path(tempfile.mkdtemp(prefix="fab-insight-browser-"))
    try:
        print(stage_message("snapshot-preparation", status="start", root=temporary), flush=True)
        from local_openai_protocol_fixture import LocalOpenAIProtocolFixture
        with LocalOpenAIProtocolFixture("compatibility", compatibility_fixture_port(args.port)) as fixture:
            environment = browser_test_environment(temporary)
            environment["FAB_BROWSER_TEST_COMPATIBILITY_BASE_URL"] = fixture.base_url
            print(stage_message("snapshot-preparation", status="ready", root=temporary), flush=True)
            os.environ.clear()
            os.environ.update(environment)
            os.chdir(PROJECT_DIR)
            install_browser_test_compatibility_key()
            print(stage_message("port-start", host="127.0.0.1", port=args.port), flush=True)
            run_server(args.port)
    finally:
        if temporary.exists():
            scan_browser_test_artifacts(temporary)
        shutil.rmtree(temporary, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
