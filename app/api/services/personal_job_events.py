from __future__ import annotations

import asyncio
import inspect
import json

from ...personal_knowledge import list_personal_job_snapshots


PERSONAL_JOB_ACTIVE_STATUSES = frozenset(
    {"uploaded", "parsing", "chunking", "indexing", "deleting"}
)


def personal_job_event_id(job: dict) -> str:
    """A line-safe identifier; reconnection always replays the current snapshot."""
    return f"{job['job_id']}-{job['updated_at']}".replace("\r", "").replace("\n", "")


def encode_personal_job_event(job: dict) -> str:
    data = json.dumps(job, ensure_ascii=False, separators=(",", ":"))
    return (
        f"retry: 1200\nid: {personal_job_event_id(job)}\nevent: job\ndata: {data}\n\n"
    )


def personal_job_snapshot_fingerprint(job: dict) -> str:
    return json.dumps(job, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def iter_personal_job_events(
    owner_user_id: str,
    *,
    snapshot_reader=list_personal_job_snapshots,
    sleep=asyncio.sleep,
    is_disconnected=None,
    poll_seconds: float = 0.5,
    heartbeat_seconds: float = 15.0,
):
    """Yield snapshots and changes without retaining cross-user event history."""
    snapshots = snapshot_reader(owner_user_id)
    if inspect.isawaitable(snapshots):
        snapshots = await snapshots
    known = {job["job_id"]: personal_job_snapshot_fingerprint(job) for job in snapshots}
    for job in snapshots:
        yield encode_personal_job_event(job)
    if not any(job["status"] in PERSONAL_JOB_ACTIVE_STATUSES for job in snapshots):
        return
    quiet_for = 0.0
    while True:
        await sleep(poll_seconds)
        if is_disconnected is not None and await is_disconnected():
            return
        snapshots = snapshot_reader(owner_user_id)
        if inspect.isawaitable(snapshots):
            snapshots = await snapshots
        changed = False
        for job in snapshots:
            fingerprint = personal_job_snapshot_fingerprint(job)
            if known.get(job["job_id"]) != fingerprint:
                known[job["job_id"]] = fingerprint
                changed = True
                yield encode_personal_job_event(job)
        if not any(job["status"] in PERSONAL_JOB_ACTIVE_STATUSES for job in snapshots):
            return
        quiet_for = 0.0 if changed else quiet_for + poll_seconds
        if quiet_for >= heartbeat_seconds:
            quiet_for = 0.0
            yield ": heartbeat\n\n"


async def read_personal_job_snapshots(owner_user_id: str) -> list[dict]:
    return await asyncio.to_thread(list_personal_job_snapshots, owner_user_id)
