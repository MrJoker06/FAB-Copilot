"""Exercise actual static responses without importing app.main or opening databases."""
import asyncio
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from app.api.application import create_application


class PassThrough:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


@asynccontextmanager
async def no_lifespan(app):
    yield


class DisplayMaterialsTests(unittest.TestCase):
    def make_app(self, root):
        return create_application(
            lifespan=no_lifespan,
            project_dir=root,
            principal_context_middleware=PassThrough,
            request_audit_middleware=PassThrough,
        )

    def test_real_materials_and_all_report_links_are_readable(self):
        root = Path(__file__).resolve().parents[1]

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.make_app(root)), base_url='http://local') as client:
                response = await client.get('/display_mock_data/catalog.json')
                self.assertEqual(response.status_code, 200)
                catalog = response.json()
                self.assertTrue(catalog['synthetic'])
                self.assertEqual(len(catalog['reports']), 6)
                self.assertEqual(len(catalog['documents']), 6)
                ids = {item['id'] for item in catalog['documents']}
                for item in catalog['documents']:
                    if item.get('related_sop'):
                        self.assertIn(item['related_sop'], ids)
                for item in catalog['reports']:
                    report = await client.get(item['url'])
                    self.assertEqual(report.status_code, 200)
                    self.assertIn(item['title'], report.text)
                    self.assertIn('<table>', report.text)
                    self.assertIn('no-cache', report.headers['cache-control'])
                    self.assertNotIn('演示', report.text)

        asyncio.run(run())

    def test_optional_directory_missing_and_path_escape_are_404(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root/'app/static').mkdir(parents=True)
            outside = root/'private.json'
            outside.write_text(json.dumps({'private': 'not public'}), encoding='utf-8')

            async def run():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.make_app(root)), base_url='http://local') as client:
                    self.assertEqual((await client.get('/display_mock_data/catalog.json')).status_code, 404)
                (root/'display_mock_data').mkdir()
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.make_app(root)), base_url='http://local') as client:
                    for path in ['/display_mock_data/%2e%2e/private.json', '/display_mock_data/missing.json']:
                        response = await client.get(path)
                        self.assertEqual(response.status_code, 404)
                        self.assertNotIn('not public', response.text)

            asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
