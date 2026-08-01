from __future__ import annotations

import re
import unittest

from app.config import APP_VERSION
from app.main import render_versioned_page


class VersionContractTests(unittest.TestCase):
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
