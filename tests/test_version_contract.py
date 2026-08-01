from __future__ import annotations

import re
import unittest
from pathlib import Path

from app.config import APP_VERSION
from app.main import render_versioned_page


class VersionContractTests(unittest.TestCase):
    def test_personal_knowledge_upload_workspace_contract(self):
        html = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")

        upload_input = re.search(r'<input id="knowledgeUploadFile"[^>]*>', html)
        self.assertIsNotNone(upload_input)
        self.assertRegex(upload_input.group(0), r'\bmultiple\b')
        self.assertNotRegex(upload_input.group(0), r'\brequired\b')
        self.assertNotIn('id="openKnowledgeUpload"', html)
        self.assertIn('id="personalKnowledgeAdd"', html)
        self.assertIn('id="knowledgeUploadQueue"', html)
        self.assertIn('/static/personal_upload_queue.js?v=__APP_VERSION__', html)
        self.assertIn('/static/personal_knowledge_metadata.js?v=__APP_VERSION__', html)
        self.assertIn('id="editPersonalKnowledge"', html)
        self.assertIn('id="personalKnowledgeMetadataDialog"', html)
        self.assertNotIn('id="renamePersonalKnowledge"', html)
        self.assertNotIn('id="personalKnowledgeRenameDialog"', html)
        self.assertNotIn('id="knowledgeUploadTitle"', html)
        script = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("${tags || '无标签'}", script)
        self.assertIn("信息已保存，但列表刷新失败", script)

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
