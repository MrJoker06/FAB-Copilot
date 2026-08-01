from __future__ import annotations

import re
import unittest
from pathlib import Path

from app.config import APP_VERSION
from app.main import render_versioned_page


class VersionContractTests(unittest.TestCase):
    def test_personal_knowledge_upload_accepts_multiple_files(self):
        html = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertRegex(html, r'<input id="knowledgeUploadFile"[^>]*\bmultiple\b')
        self.assertIn("选择一个或多个文件，或拖放到这里", html)
        self.assertIn("单文件最大 50 MB", html)

    def test_batch_upload_clears_failed_batch_before_refreshing_personal_knowledge(self):
        script = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")

        clear_selection = script.index("$('#knowledgeUploadFile').value = '';")
        refresh_knowledge = script.index("await setKnowledgeMode('personal');", clear_selection)
        self.assertLess(clear_selection, refresh_knowledge)
        self.assertIn("const uploadSummary = `已成功上传 ${successes.length} 个，失败 ${failures.length} 个。", script)
        self.assertIn("列表刷新失败：${error.message}", script)
        self.assertIn("let dialogClosedAfterFullSuccess = false;", script)
        self.assertIn("已上传 ${successes.length} 个文档，但列表刷新失败：${error.message}", script)

    def test_rendered_pages_share_the_active_build_version(self):
        for page in ("index", "admin"):
            with self.subTest(page=page):
                response = render_versioned_page(page)
                html = response.body.decode("utf-8")
                resource_versions = re.findall(r'(?:href|src)="/static/[^"?]+\?v=([^"&]+)"', html)

                self.assertEqual(response.headers["cache-control"], "no-cache, no-store, must-revalidate")
                self.assertIn(f'<meta name="app-version" content="{APP_VERSION}">', html)
                self.assertTrue(resource_versions)
                self.assertTrue(all(version == APP_VERSION for version in resource_versions))
                self.assertNotIn("__APP_VERSION__", html)
                self.assertNotIn("20260801-2", html)
                self.assertNotIn("20260718-3", html)
