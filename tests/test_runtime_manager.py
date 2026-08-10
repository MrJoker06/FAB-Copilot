from __future__ import annotations

import fcntl
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.manage_runtime import (
    apply_prune_plan,
    build_prune_plan,
    discover_instances,
    inspect_instance,
    remove_inactive_instance,
)


class RuntimeManagerTests(unittest.TestCase):
    def create_instance(self, root: Path, name: str, age_days: int) -> Path:
        path = root / name
        path.mkdir()
        manifest = path / "instance.json"
        manifest.write_text(
            json.dumps({"instance_id": name, "git_commit": name[-4:], "port": 8888}),
            encoding="utf-8",
        )
        (path / "service.lock").touch()
        (path / "data.bin").write_bytes(b"x" * 32)
        timestamp = (datetime.now(timezone.utc) - timedelta(days=age_days)).timestamp()
        os.utime(manifest, (timestamp, timestamp))
        return path

    def test_plan_keeps_newest_and_active_instances(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            newest = self.create_instance(root, "instance-new", 0)
            active = self.create_instance(root, "instance-active", 5)
            old = self.create_instance(root, "instance-old", 6)
            with (active / "service.lock").open("r+") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                instances = discover_instances(root)
                plan = build_prune_plan(instances, keep=1, older_than_days=3, protected_ids=set())
            decisions = {item["instance_id"]: (item["action"], item["reason"]) for item in plan}
            self.assertEqual(decisions[newest.name], ("keep", "newest_retention"))
            self.assertEqual(decisions[active.name], ("keep", "active"))
            self.assertEqual(decisions[old.name], ("delete", "eligible"))

    def test_apply_only_removes_planned_child_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.create_instance(root, "instance-new", 0)
            old = self.create_instance(root, "instance-old", 6)
            plan = build_prune_plan(discover_instances(root), 1, 3, set())
            removed = apply_prune_plan(root, plan)
            self.assertEqual(removed, [old.name])
            self.assertFalse(old.exists())

    def test_remove_refuses_instance_with_held_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = self.create_instance(root, "instance-active", 6)
            with (active / "service.lock").open("r+") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertFalse(remove_inactive_instance(active))
            self.assertTrue(active.exists())

    def test_invalid_manifest_missing_lock_and_boundaries_are_kept(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = root / "invalid"
            invalid.mkdir()
            (invalid / "instance.json").write_text("{broken", encoding="utf-8")
            newest = self.create_instance(root, "newest", 0)
            boundary = self.create_instance(root, "boundary", 3)
            (boundary / "service.lock").unlink()
            now = datetime.now(timezone.utc)
            os.utime(boundary / "instance.json", ((now - timedelta(days=3)).timestamp(),) * 2)
            plan = build_prune_plan(discover_instances(root), 1, 3, {"boundary"}, now=now)
            decisions = {item["instance_id"]: (item["action"], item["reason"]) for item in plan}
            self.assertEqual(decisions[invalid.name], ("keep", "invalid_manifest"))
            self.assertEqual(decisions[newest.name], ("keep", "newest_retention"))
            self.assertEqual(decisions[boundary.name], ("keep", "explicitly_protected"))
            self.assertFalse(inspect_instance(boundary).active)

    def test_apply_refuses_symlink_outside_root_and_id_path_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "runtime"
            root.mkdir()
            outside = Path(temporary) / "outside"
            outside.mkdir()
            (outside / "service.lock").touch()
            link = root / "linked"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                apply_prune_plan(root, [{"action": "delete", "path": str(link), "instance_id": "linked"}])
            child = self.create_instance(root, "child", 10)
            with self.assertRaises(RuntimeError):
                apply_prune_plan(root, [{"action": "delete", "path": str(child), "instance_id": "other"}])
            self.assertTrue(outside.exists())
            self.assertTrue(child.exists())

    def test_apply_does_not_remove_delete_candidate_when_lock_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self.create_instance(root, "candidate", 10)
            plan = build_prune_plan(discover_instances(root), 0, 0, set())
            (candidate / "service.lock").unlink()
            self.assertEqual(apply_prune_plan(root, plan), [])
            self.assertTrue(candidate.exists())

    def test_apply_refuses_stale_plan_after_manifest_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.create_instance(root, "newest", 0)
            candidate = self.create_instance(root, "candidate", 10)
            plan = build_prune_plan(discover_instances(root), 1, 0, set())
            manifest_path = candidate / "instance.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["port"] = 9999
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "changed or unsafe"):
                apply_prune_plan(root, plan)
            self.assertTrue(candidate.exists())


if __name__ == "__main__":
    unittest.main()
