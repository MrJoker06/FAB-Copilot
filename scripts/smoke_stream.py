from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterable
from typing import Any

import httpx


DEFAULT_URL = "http://127.0.0.1:8888/api/chat/stream"


def summarize_events(lines: Iterable[str]) -> dict[str, Any]:
    """Parse an NDJSON stream without making a network or model request."""
    event_index = 0
    first_answer_index = None
    tool_events = 0
    tools_after_answer = 0
    answer_chunks = 0
    session_id = None
    run_id = None
    result_received = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        event_index += 1
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid NDJSON event at index {event_index}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"NDJSON event at index {event_index} must be an object")
        if event.get("type") == "session":
            session_id = event.get("session_id")
        if event.get("event") == "run_started":
            run_id = event.get("run_id")
        if event.get("event") in {"tool_started", "tool_finished"}:
            tool_events += 1
            if first_answer_index is not None:
                tools_after_answer += 1
        if event.get("event") == "answer_delta":
            answer_chunks += 1
            first_answer_index = first_answer_index or event_index
        if event.get("type") == "result":
            result_received = True

    return {
        "session_id": session_id,
        "run_id": run_id,
        "events": event_index,
        "tool_events": tool_events,
        "answer_chunks": answer_chunks,
        "first_answer_event": first_answer_index,
        "tools_after_first_answer": tools_after_answer,
        "result_received": result_received,
    }


def validation_errors(summary: dict[str, Any]) -> list[str]:
    errors = []
    if not summary["result_received"]:
        errors.append("result event was not received")
    if not summary["answer_chunks"]:
        errors.append("answer_delta event was not received")
    if summary["tools_after_first_answer"]:
        errors.append("tool event appeared after the first answer_delta event")
    return errors


def run_smoke(
    question: str,
    url: str,
    transport: Callable[..., Any] = httpx.stream,
) -> tuple[dict[str, Any], list[str]]:
    with transport("POST", url, json={"message": question}, timeout=120) as response:
        response.raise_for_status()
        summary = summarize_events(response.iter_lines())
    return summary, validation_errors(summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Fab Insight NDJSON stream ordering")
    parser.add_argument("question", nargs="?", default="分析 CVD-02 最近90天膜厚漂移")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args(argv)

    try:
        summary, errors = run_smoke(args.question, args.url)
    except httpx.HTTPError:
        print(json.dumps({"error": "HTTP request failed"}, ensure_ascii=False))
        return 1
    except ValueError:
        print(json.dumps({"error": "Invalid NDJSON stream"}, ensure_ascii=False))
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors:
        print(json.dumps({"errors": errors}, ensure_ascii=False), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
