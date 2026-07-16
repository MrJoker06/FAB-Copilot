from __future__ import annotations

import argparse

import httpx


def smoke(base_url: str) -> dict[str, object]:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        ready = client.get("/api/v1/health/ready")
        ready.raise_for_status()
        dashboard = client.get("/api/v1/reports/dashboard")
        dashboard.raise_for_status()
        knowledge = client.get("/api/v1/knowledge/documents")
        knowledge.raise_for_status()
        cases = client.get("/api/v1/cases")
        cases.raise_for_status()
        chat = client.post("/api/v1/chat", json={"message": "概览当前工厂情况与近期异常"})
        chat.raise_for_status()
        chat_data = chat.json()["data"]
        session_id = chat_data["session_id"]
        session = client.get(f"/api/v1/sessions/{session_id}")
        session.raise_for_status()
        cleanup = client.delete(f"/api/v1/sessions/{session_id}/permanent")
        cleanup.raise_for_status()
    overview = dashboard.json()["data"]["overview"]
    return {
        "ready": ready.json()["data"]["status"],
        "lots": overview["lots"],
        "knowledge_documents": len(knowledge.json()["data"]),
        "cases": len(cases.json()["data"]),
        "chat_mode": chat_data["mode"],
        "chat_tools": [item["tool"] for item in chat_data["tool_trace"]],
        "persisted_messages": len(session.json()["data"]["messages"]),
        "cleanup": cleanup.json()["data"]["deleted"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test a running Fab Insight V2 API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    print(smoke(args.base_url))


if __name__ == "__main__":
    main()
