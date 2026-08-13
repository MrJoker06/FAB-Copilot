from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException

from app.main import (
    app,
    current_personal_user,
    encode_personal_job_event,
    iter_personal_job_events,
    personal_job_event_id,
    personal_knowledge_job_events,
    read_personal_job_snapshots,
)
from app.personal_knowledge import list_personal_job_snapshots


def job(status="indexing", updated_at="2026-08-13T12:00:00+00:00"):
    return {
        "job_id": "job-1",
        "document_id": "doc-1",
        "status": status,
        "stage": status,
        "progress": 50,
        "attempt": 1,
        "error": None,
        "created_at": updated_at,
        "updated_at": updated_at,
    }


class PersonalJobSseTests(unittest.TestCase):
    def test_configured_token_rejects_wrong_personal_user(self):
        settings = type('Settings', (), {'personal_knowledge_api_token': 'expected'})()
        with patch('app.main.get_settings', return_value=settings):
            with self.assertRaises(HTTPException) as raised:
                current_personal_user('Bearer wrong')
        self.assertEqual(raised.exception.status_code, 401)

    def test_snapshots_are_owner_scoped_latest_and_active_first(self):
        with tempfile.NamedTemporaryFile() as database:
            connection = sqlite3.connect(database.name)
            connection.row_factory = sqlite3.Row
            connection.execute(
                """CREATE TABLE personal_knowledge_jobs (
                    job_id, document_id, owner_user_id, status, stage, progress, attempt,
                    error_code, error_message, retryable, created_at, updated_at)"""
            )
            rows = [
                ('old', 'a', 'owner-a', 'ready', 'done', 100, 1, None, None, 0, '1', '1'),
                ('new', 'a', 'owner-a', 'indexing', 'index', 50, 2, None, None, 0, '2', '2'),
                ('ready', 'b', 'owner-a', 'ready', 'done', 100, 1, None, None, 0, '3', '3'),
                ('other', 'c', 'owner-b', 'indexing', 'index', 50, 1, None, None, 0, '4', '4'),
            ]
            connection.executemany(
                "INSERT INTO personal_knowledge_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            connection.commit()

            @contextmanager
            def session():
                yield connection

            with patch('app.personal_knowledge.db_session', session):
                snapshots = list_personal_job_snapshots('owner-a')
            connection.close()

        self.assertEqual([item['job_id'] for item in snapshots], ['new', 'ready'])
        self.assertNotIn('owner_user_id', snapshots[0])
        self.assertNotIn('error_code', snapshots[0])
        self.assertNotIn('storage_path', snapshots[0])

    def test_encode_is_line_safe_and_public(self):
        event = encode_personal_job_event(job(updated_at="when\nnow"))
        self.assertIn("event: job\n", event)
        self.assertIn("retry: 1200\n", event)
        self.assertNotIn("owner_user_id", event)
        self.assertNotIn("storage_path", event)
        self.assertNotIn("\nid: job-1-when\nnow", event)
        self.assertEqual(personal_job_event_id(job()), "job-1-2026-08-13T12:00:00+00:00")

    def test_initial_terminal_snapshot_finishes(self):
        async def collect():
            return [
                item
                async for item in iter_personal_job_events(
                    "owner",
                    snapshot_reader=lambda _: [job("ready")],
                )
            ]

        emitted = asyncio.run(collect())
        self.assertEqual(len(emitted), 1)
        self.assertIn('"status":"ready"', emitted[0])

    def test_events_route_contract_and_static_precedence(self):
        class Request:
            async def is_disconnected(self):
                return False

        request = Request()

        async def snapshot_reader(_):
            return [job('ready')]

        with patch('app.main.read_personal_job_snapshots', snapshot_reader):
            response, emitted = asyncio.run(_route_output(request))

        self.assertEqual(response.media_type, 'text/event-stream')
        self.assertEqual(response.headers['cache-control'], 'no-cache')
        self.assertEqual(response.headers['x-accel-buffering'], 'no')
        self.assertIn('event: job', emitted[0])
        paths = [route.path for route in app.routes]
        self.assertLess(
            paths.index('/api/knowledge/personal/jobs/events'),
            paths.index('/api/knowledge/jobs/{job_id}'),
        )

    def test_threadpool_snapshot_reader(self):
        calls = []

        async def to_thread(function, *args):
            calls.append((function, args))
            return [job('ready')]

        with patch('app.main.asyncio.to_thread', to_thread):
            snapshots = asyncio.run(read_personal_job_snapshots('owner'))
        self.assertEqual(calls[0][1], ('owner',))
        self.assertEqual(snapshots[0]['document_id'], 'doc-1')

    def test_change_and_heartbeat_are_observable(self):
        snapshots = [[job()], [job()], [job("ready", "2026-08-13T12:00:01+00:00")]]

        def reader(_):
            return snapshots.pop(0) if snapshots else [job("ready", "2026-08-13T12:00:01+00:00")]

        async def no_sleep(_):
            pass

        async def collect():
            return [
                item
                async for item in iter_personal_job_events(
                    "owner",
                    snapshot_reader=reader,
                    sleep=no_sleep,
                    poll_seconds=15,
                    heartbeat_seconds=15,
                )
            ]

        emitted = asyncio.run(collect())
        self.assertIn(": heartbeat", emitted[1])
        self.assertIn('"status":"ready"', emitted[2])


async def _collect(iterator):
    return [item async for item in iterator]


async def _route_output(request):
    response = await personal_knowledge_job_events(request, 'owner', 'old-id')
    return response, await _collect(response.body_iterator)
