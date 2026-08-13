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
        self.assertNotIn('id="personalKnowledgeAdd"', html)
        self.assertIn('id="knowledgeUploadQueue"', html)
        self.assertIn('/static/personal_upload_queue.js?v=__APP_VERSION__', html)
        self.assertIn('/static/personal_knowledge_metadata.js?v=__APP_VERSION__', html)
        self.assertIn('/static/personal_job_events.js?v=__APP_VERSION__', html)
        self.assertIn('/static/thinking_control.js?v=__APP_VERSION__', html)
        self.assertIn('id="thinkingToggle"', html)
        self.assertIn('id="editPersonalKnowledge"', html)
        self.assertIn('id="personalKnowledgeMetadataDialog"', html)
        self.assertNotIn('id="renamePersonalKnowledge"', html)
        self.assertNotIn('id="personalKnowledgeRenameDialog"', html)
        self.assertNotIn('id="knowledgeUploadTitle"', html)
        self.assertIn('.png,.jpg,.jpeg,.tif,.tiff', upload_input.group(0))
        script = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('personalKnowledgeAdd', script)
        self.assertIn('personal-knowledge-upload-more', script)
        self.assertIn('data-open-knowledge-upload', script)
        self.assertIn("${tags || '无标签'}", script)
        self.assertIn("信息已保存，但列表刷新失败", script)
        self.assertNotIn("OCR 尚未启用", script)
        self.assertIn("OCR_QUALITY_LOW", script)

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

    def test_admin_compatibility_contract(self):
        root = Path(__file__).parents[1] / "app" / "static"
        html = (root / "admin.html").read_text(encoding="utf-8")
        script = (root / "admin.js").read_text(encoding="utf-8")
        self.assertIn('id="editCapabilitiesDialog"', html)
        self.assertIn("能力探针仅在主动执行时联网", html)
        self.assertIn('data-action="compatibility"', script)
        self.assertIn('data-action="capabilities"', script)
        self.assertIn("/compatibility-check", script)
        self.assertIn("/capabilities", script)
        self.assertNotIn("正在执行兼容性检查", script)
        self.assertIn("能力探针通过", script)
        self.assertIn("探针中…", script)
        self.assertIn("能力探针失败：", script)
        self.assertIn("compatibility-details", script)
