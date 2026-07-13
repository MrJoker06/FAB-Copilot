from __future__ import annotations

import argparse
import json

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Fab Insight NDJSON stream ordering")
    parser.add_argument("question", nargs="?", default="分析 CVD-02 最近90天膜厚漂移")
    parser.add_argument("--url", default="http://127.0.0.1:8765/api/chat/stream")
    args = parser.parse_args()

    event_index = 0
    first_answer_index = None
    tool_events = 0
    tools_after_answer = 0
    answer_chunks = 0
    session_id = None
    run_id = None
    result_received = False
    with httpx.stream(
        "POST",
        args.url,
        json={"message": args.question},
        timeout=120,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.strip():
                continue
            event_index += 1
            event = json.loads(line)
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

    summary = {
        "session_id": session_id,
        "run_id": run_id,
        "events": event_index,
        "tool_events": tool_events,
        "answer_chunks": answer_chunks,
        "first_answer_event": first_answer_index,
        "tools_after_first_answer": tools_after_answer,
        "result_received": result_received,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not result_received or not answer_chunks or tools_after_answer:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
